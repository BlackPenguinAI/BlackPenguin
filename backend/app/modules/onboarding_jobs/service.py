from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db.postgres import SessionLocal
from app.modules.onboarding_questions import build_next_question

from .models import OnboardingSourceJob
from .healthcheck import write_heartbeat

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def _safe_error_detail(value: object) -> str:
    detail = str(value or "source_processing_failed")
    detail = re.sub(r"https?://\S+", "<url>", detail, flags=re.IGNORECASE)
    detail = re.sub(
        r"(?i)(bearer\s+|sk-or-v1-)[a-z0-9._-]+",
        lambda match: f"{match.group(1)}<redacted>",
        detail,
    )
    return detail[:300]


def _safe_exc_info(exc: Exception):
    redacted = RuntimeError(f"{type(exc).__name__}: {_safe_error_detail(exc)}")
    return type(redacted), redacted, exc.__traceback__


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host + port, path, parts.query, ""))


def enqueue(
    db: Session, *, scope: str, company_id: str, source_id: str, url: str,
    session_id: str, project_id: str | None = None, message_id: str | None = None,
    commit: bool = True,
) -> OnboardingSourceJob:
    raw_key = "|".join((scope, project_id or company_id, normalize_url(url), session_id))
    key = hashlib.sha256(raw_key.encode()).hexdigest()
    existing = db.query(OnboardingSourceJob).filter(OnboardingSourceJob.idempotency_key == key).first()
    if existing and existing.status in {"queued", "processing", "completed"}:
        return existing
    if existing and existing.status == "failed":
        existing.status = "queued"
        existing.attempts = 0
        existing.available_at = datetime.utcnow()
        existing.started_at = None
        existing.completed_at = None
        existing.error_code = None
        existing.error_detail = None
        db.add(existing)
        if commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing
    job = OnboardingSourceJob(
        scope=scope, company_id=company_id, project_id=project_id, source_id=source_id,
        message_id=message_id, idempotency_key=key, status="queued",
    )
    if not commit:
        try:
            with db.begin_nested():
                db.add(job)
                db.flush()
            return job
        except IntegrityError:
            return db.query(OnboardingSourceJob).filter(
                OnboardingSourceJob.idempotency_key == key
            ).one()
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        return db.query(OnboardingSourceJob).filter(OnboardingSourceJob.idempotency_key == key).one()


def deduplicate_source(db: Session, job: OnboardingSourceJob, source, *, commit: bool = True):
    """Remove a just-created duplicate source when an idempotent job already exists."""
    if job.source_id == source.id:
        return source
    model = type(source)
    db.delete(source)
    if commit:
        db.commit()
    else:
        db.flush()
    return db.query(model).filter(model.id == job.source_id).one()


def retry_job(db: Session, *, scope: str, source_id: str) -> OnboardingSourceJob | None:
    job = db.query(OnboardingSourceJob).filter(
        OnboardingSourceJob.scope == scope,
        OnboardingSourceJob.source_id == source_id,
    ).order_by(OnboardingSourceJob.created_at.desc()).first()
    if not job:
        return None
    if job.status in {"queued", "processing"}:
        return job
    job.status = "queued"
    job.attempts = 0
    job.available_at = datetime.utcnow()
    job.started_at = None
    job.completed_at = None
    job.error_code = None
    job.error_detail = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def run_worker(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await run_iteration()
        except Exception as exc:
            logger.error(
                "onboarding_worker_iteration_failed error_type=%s",
                type(exc).__name__,
                exc_info=_safe_exc_info(exc),
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def run_iteration() -> bool:
    processed = await run_once()
    write_heartbeat()
    return processed


async def run_once() -> bool:
    db = SessionLocal()
    try:
        job = _claim(db)
        # A successful claim query proves that the worker can reach PostgreSQL.
        # Refresh before processing because scraping and LLM calls can take time.
        write_heartbeat()
        if not job:
            return False
        await _process(db, job)
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _claim(db: Session) -> OnboardingSourceJob | None:
    now = datetime.utcnow()
    abandoned_before = datetime.utcnow() - timedelta(minutes=5)
    job = db.query(OnboardingSourceJob).filter(
        ((OnboardingSourceJob.status == "queued") & (OnboardingSourceJob.available_at <= now))
        | ((OnboardingSourceJob.status == "processing") & (OnboardingSourceJob.started_at < abandoned_before))
    ).order_by(OnboardingSourceJob.created_at.asc()).with_for_update(skip_locked=True).first()
    if not job:
        return None
    job.status = "processing"
    job.attempts += 1
    job.started_at = now
    job.error_code = None
    db.add(job); db.commit(); db.refresh(job)
    logger.info(
        "onboarding_job_claimed job_id=%s scope=%s source_id=%s attempt=%s",
        job.id, job.scope, job.source_id, job.attempts,
    )
    return job


async def _process(db: Session, job: OnboardingSourceJob) -> None:
    started = time.monotonic()
    logger.info(
        "onboarding_job_started job_id=%s scope=%s source_id=%s attempt=%s",
        job.id, job.scope, job.source_id, job.attempts,
    )
    try:
        if job.scope == "company":
            await _process_company(db, job)
        elif job.scope == "project":
            await _process_project(db, job)
        else:
            raise ValueError("unknown_scope")
        job.status = "completed"; job.completed_at = datetime.utcnow(); job.error_detail = None
        logger.info(
            "onboarding_job_completed job_id=%s scope=%s source_id=%s attempt=%s duration_ms=%s",
            job.id, job.scope, job.source_id, job.attempts,
            int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        db.rollback()
        job = db.query(OnboardingSourceJob).filter(OnboardingSourceJob.id == job.id).first()
        if not job:
            return
        job.status = "queued" if job.attempts < MAX_ATTEMPTS else "failed"
        job.error_code = type(exc).__name__[:80]
        job.error_detail = "Processing failed; use the job id to correlate server logs."
        if job.status == "failed":
            job.completed_at = datetime.utcnow()
            _mark_source_failed(db, job)
            _save_terminal_failure_message(db, job)
        else:
            job.available_at = datetime.utcnow() + timedelta(seconds=2 ** job.attempts)
        logger.error(
            "onboarding_job_failed job_id=%s scope=%s source_id=%s attempt=%s "
            "error_type=%s final=%s duration_ms=%s",
            job.id, job.scope, job.source_id, job.attempts,
            type(exc).__name__, job.status == "failed",
            int((time.monotonic() - started) * 1000),
            exc_info=_safe_exc_info(exc),
        )
    db.add(job)
    db.commit()


def _mark_source_failed(db: Session, job: OnboardingSourceJob) -> None:
    if job.scope == "company":
        from app.modules.company_onboarding.models import CompanyOnboardingSource, SourceStatus

        source = db.query(CompanyOnboardingSource).filter(
            CompanyOnboardingSource.id == job.source_id,
            CompanyOnboardingSource.company_id == job.company_id,
        ).first()
        failed_status = SourceStatus.FAILED
    else:
        from app.modules.projects.models import ProjectOnboardingSource, ProjectSourceStatus

        source = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.id == job.source_id,
            ProjectOnboardingSource.project_id == job.project_id,
        ).first()
        failed_status = ProjectSourceStatus.FAILED
    if source:
        source.status = failed_status
        source.error_message = "The website could not be processed after several attempts."
        db.add(source)


def _save_terminal_failure_message(db: Session, job: OnboardingSourceJob) -> None:
    content = (
        "I couldn't process that website after several attempts. "
        "You can retry the source or continue the onboarding manually."
    )
    ui_payload = {
        "kind": "source_processing_failed",
        "source_id": job.source_id,
        "actions": ["retry", "continue"],
    }
    try:
        with db.begin_nested():
            if job.scope == "company":
                from app.modules.company_onboarding import services
                from app.modules.company_onboarding.models import OnboardingSession, SenderType

                session = db.query(OnboardingSession).filter(
                    OnboardingSession.company_id == job.company_id
                ).first()
                if session:
                    services.save_message(
                        db, session.id, SenderType.AI, content,
                        ui_payload=ui_payload, commit=False,
                    )
            elif job.scope == "project":
                from app.modules.projects import services
                from app.modules.projects.models import SenderType

                project = services.get_project(db, job.project_id or "", job.company_id)
                services.save_message(
                    db, project.session.id, SenderType.AI, content,
                    ui_payload=ui_payload, commit=False,
                )
    except Exception as exc:
        logger.error(
            "onboarding_terminal_message_failed job_id=%s scope=%s source_id=%s error_type=%s",
            job.id, job.scope, job.source_id, type(exc).__name__,
            exc_info=_safe_exc_info(exc),
        )


async def _process_company(db: Session, job: OnboardingSourceJob) -> None:
    from app.modules.company_onboarding import services, source_service
    from app.modules.company_onboarding.models import (
        CompanyOnboardingProposal,
        CompanyOnboardingSource,
        ProposalStatus,
        SenderType,
    )

    source = db.query(CompanyOnboardingSource).filter(
        CompanyOnboardingSource.id == job.source_id,
        CompanyOnboardingSource.company_id == job.company_id,
    ).first()
    if not source: raise ValueError("source_not_found")
    if source.status.value == "failed" and job.attempts < MAX_ATTEMPTS:
        source.status = source.status.__class__.PROCESSING; source.error_message = None
        db.add(source); db.commit(); db.refresh(source)
    await source_service.process_url_source(db, source)
    if source.status.value == "failed":
        raise ValueError(f"source_processing_failed: {_safe_error_detail(source.error_message)}")
    session = services.get_or_create_session(db, job.company_id)
    pending_proposals = db.query(CompanyOnboardingProposal).filter(
        CompanyOnboardingProposal.source_id == source.id,
        CompanyOnboardingProposal.status == ProposalStatus.PENDING,
    ).count()
    if pending_proposals:
        services.save_message(
            db,
            session.id,
            SenderType.AI,
            f"I extracted {pending_proposals} proposal{'s' if pending_proposals != 1 else ''} "
            f"from **{source.name}**. Review them before we continue.",
            in_reply_to_message_id=job.message_id,
        )
        return
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
        in_reply_to_message_id=job.message_id,
    )


async def _process_project(db: Session, job: OnboardingSourceJob) -> None:
    from app.modules.projects import services, source_service
    from app.modules.projects.models import (
        ProjectOnboardingProposal,
        ProjectOnboardingSource,
        ProjectProposalStatus,
        SenderType,
    )

    project = services.get_project(db, job.project_id or "", job.company_id)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == job.source_id,
        ProjectOnboardingSource.project_id == project.id,
    ).first()
    if not source: raise ValueError("source_not_found")
    if source.status.value == "failed" and job.attempts < MAX_ATTEMPTS:
        source.status = source.status.__class__.PROCESSING; source.error_message = None
        db.add(source); db.commit(); db.refresh(source)
    await source_service.process_url_source(db, source)
    if source.status.value == "failed":
        raise ValueError(f"source_processing_failed: {_safe_error_detail(source.error_message)}")
    pending_proposals = db.query(ProjectOnboardingProposal).filter(
        ProjectOnboardingProposal.source_id == source.id,
        ProjectOnboardingProposal.status == ProjectProposalStatus.PENDING,
    ).count()
    if pending_proposals:
        services.save_message(
            db,
            project.session.id,
            SenderType.AI,
            f"I extracted {pending_proposals} proposal{'s' if pending_proposals != 1 else ''} "
            f"from **{source.name}**. Review them before we continue.",
            in_reply_to_message_id=job.message_id,
        )
        return
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
        in_reply_to_message_id=job.message_id,
    )
