from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.postgres import SessionLocal
from app.modules.onboarding_questions import build_next_question

from .models import OnboardingSourceJob


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))


def enqueue(
    db: Session, *, scope: str, company_id: str, source_id: str, url: str,
    session_id: str, project_id: str | None = None, message_id: str | None = None,
) -> OnboardingSourceJob:
    raw_key = "|".join((scope, project_id or company_id, normalize_url(url), session_id))
    key = hashlib.sha256(raw_key.encode()).hexdigest()
    existing = db.query(OnboardingSourceJob).filter(OnboardingSourceJob.idempotency_key == key).first()
    if existing and existing.status in {"queued", "processing", "completed"}:
        return existing
    job = OnboardingSourceJob(
        scope=scope, company_id=company_id, project_id=project_id, source_id=source_id,
        message_id=message_id, idempotency_key=key, status="queued",
    )
    db.add(job)
    try:
        db.commit(); db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        return db.query(OnboardingSourceJob).filter(OnboardingSourceJob.idempotency_key == key).one()


def deduplicate_source(db: Session, job: OnboardingSourceJob, source):
    """Remove a just-created duplicate source when an idempotent job already exists."""
    if job.source_id == source.id:
        return source
    model = type(source)
    db.delete(source); db.commit()
    return db.query(model).filter(model.id == job.source_id).one()


async def run_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            job = _claim(db)
            if job:
                await _process(db, job)
        except Exception:
            db.rollback()
        finally:
            db.close()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


def _claim(db: Session) -> OnboardingSourceJob | None:
    abandoned_before = datetime.utcnow() - timedelta(minutes=5)
    job = db.query(OnboardingSourceJob).filter(
        (OnboardingSourceJob.status == "queued")
        | ((OnboardingSourceJob.status == "processing") & (OnboardingSourceJob.started_at < abandoned_before))
    ).order_by(OnboardingSourceJob.created_at.asc()).with_for_update(skip_locked=True).first()
    if not job:
        return None
    job.status = "processing"; job.attempts += 1; job.started_at = datetime.utcnow(); job.error_code = None
    db.add(job); db.commit(); db.refresh(job)
    return job


async def _process(db: Session, job: OnboardingSourceJob) -> None:
    try:
        if job.scope == "company":
            await _process_company(db, job)
        elif job.scope == "project":
            await _process_project(db, job)
        else:
            raise ValueError("unknown_scope")
        job.status = "completed"; job.completed_at = datetime.utcnow(); job.error_detail = None
    except Exception as exc:
        db.rollback()
        job = db.query(OnboardingSourceJob).filter(OnboardingSourceJob.id == job.id).first()
        if not job:
            return
        job.status = "queued" if job.attempts < 3 else "failed"
        job.error_code = type(exc).__name__[:80]
        job.error_detail = str(exc)[:500]
        if job.status == "failed": job.completed_at = datetime.utcnow()
    db.add(job); db.commit()


async def _process_company(db: Session, job: OnboardingSourceJob) -> None:
    from app.modules.company_onboarding import services, source_service
    from app.modules.company_onboarding.models import CompanyOnboardingSource, SenderType

    source = db.query(CompanyOnboardingSource).filter(
        CompanyOnboardingSource.id == job.source_id,
        CompanyOnboardingSource.company_id == job.company_id,
    ).first()
    if not source: raise ValueError("source_not_found")
    if source.status.value == "failed" and job.attempts < 3:
        source.status = source.status.__class__.PROCESSING; source.error_message = None
        db.add(source); db.commit(); db.refresh(source)
    await source_service.process_url_source(db, source)
    if source.status.value == "failed": raise ValueError("source_processing_failed")
    session = services.get_or_create_session(db, job.company_id)
    profile = services.get_or_create_profile(db, job.company_id)
    question = build_next_question(
        services.serialize_profile(profile)["completion"]["blockers"],
        final_prompt="Review the Company Profile and choose whether to approve it or make changes.",
    )
    outcome = "processed successfully" if source.status.value == "ready" else "could not be processed"
    services.save_message(
        db, session.id, SenderType.AI,
        f"The website **{source.name}** was {outcome}. {question['prompt']}",
        ui_payload=question,
    )


async def _process_project(db: Session, job: OnboardingSourceJob) -> None:
    from app.modules.projects import services, source_service
    from app.modules.projects.models import ProjectOnboardingSource, SenderType

    project = services.get_project(db, job.project_id or "", job.company_id)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == job.source_id,
        ProjectOnboardingSource.project_id == project.id,
    ).first()
    if not source: raise ValueError("source_not_found")
    if source.status.value == "failed" and job.attempts < 3:
        source.status = source.status.__class__.PROCESSING; source.error_message = None
        db.add(source); db.commit(); db.refresh(source)
    await source_service.process_url_source(db, source)
    if source.status.value == "failed": raise ValueError("source_processing_failed")
    profile = services.get_profile(project)
    question = build_next_question(
        services.serialize_profile(profile)["completion"]["blockers"],
        final_prompt="Review the Project Profile and choose whether to approve it or make changes.",
    )
    outcome = "processed successfully" if source.status.value == "ready" else "could not be processed"
    services.save_message(
        db, project.session.id, SenderType.AI,
        f"The website **{source.name}** was {outcome}. {question['prompt']}",
        ui_payload=question,
    )
