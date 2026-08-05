from __future__ import annotations

import argparse
import json
from typing import Any

from app.db.postgres import SessionLocal
from app.modules.company_onboarding import services as company_services
from app.modules.company_onboarding.models import CompanyOnboardingSource, SourceStatus
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_jobs.service import enqueue
from app.modules.projects.models import ProjectOnboardingSource, ProjectSourceStatus


def _has_job(db, *, scope: str, source_id: str) -> bool:
    return db.query(OnboardingSourceJob).filter(
        OnboardingSourceJob.scope == scope,
        OnboardingSourceJob.source_id == source_id,
    ).first() is not None


def reconcile(*, apply: bool) -> dict[str, Any]:
    db = SessionLocal()
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "recoverable": [],
        "requeued": [],
        "marked_failed": [],
    }
    try:
        company_sources = db.query(CompanyOnboardingSource).filter(
            CompanyOnboardingSource.status == SourceStatus.PROCESSING
        ).all()
        for source in company_sources:
            if _has_job(db, scope="company", source_id=source.id):
                continue
            if not source.url:
                report["marked_failed"].append({"scope": "company", "source_id": source.id})
                if apply:
                    source.status = SourceStatus.FAILED
                    source.error_message = "The source cannot be recovered because its URL is missing."
                    db.add(source)
                continue
            report["recoverable"].append({"scope": "company", "source_id": source.id})
            if apply:
                session = company_services.get_or_create_session(db, source.company_id)
                job = enqueue(
                    db,
                    scope="company",
                    company_id=source.company_id,
                    source_id=source.id,
                    url=source.url,
                    session_id=session.id,
                    message_id=source.message_id,
                )
                report["requeued"].append({"scope": "company", "source_id": source.id, "job_id": job.id})

        project_sources = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.status == ProjectSourceStatus.PROCESSING
        ).all()
        for source in project_sources:
            if _has_job(db, scope="project", source_id=source.id):
                continue
            project = source.project
            if not source.url or not project or not project.session:
                report["marked_failed"].append({"scope": "project", "source_id": source.id})
                if apply:
                    source.status = ProjectSourceStatus.FAILED
                    source.error_message = "The source cannot be recovered because required context is missing."
                    db.add(source)
                continue
            report["recoverable"].append({"scope": "project", "source_id": source.id})
            if apply:
                job = enqueue(
                    db,
                    scope="project",
                    company_id=project.company_id,
                    project_id=project.id,
                    source_id=source.id,
                    url=source.url,
                    session_id=project.session.id,
                    message_id=source.message_id,
                )
                report["requeued"].append({"scope": "project", "source_id": source.id, "job_id": job.id})

        if apply:
            db.commit()
        else:
            db.rollback()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover onboarding sources left without a durable job.")
    parser.add_argument("--apply", action="store_true", help="Persist recovery actions. Default is dry-run.")
    args = parser.parse_args()
    print(json.dumps(reconcile(apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
