"""Idempotently encrypt legacy project and meeting files after the compliance migration.

Run first in dry-run mode, then apply during a maintenance window:
  python -m app.scripts.encrypt_existing_materials
  python -m app.scripts.encrypt_existing_materials --apply
"""
from __future__ import annotations

import argparse

from app.db import base as _model_registry  # noqa: F401
from app.db.postgres import SessionLocal
from app.modules.company_onboarding import storage_service as company_storage
from app.modules.company_onboarding.models import CompanyMediaAsset, CompanyOnboardingSource
from app.modules.projects import storage_service as project_storage
from app.modules.projects.models import ProjectOnboardingSource
from app.modules.sales_crm import storage_service as meeting_storage
from app.modules.sales_crm.models import MeetingAttachment


def encrypt_existing_materials(*, apply: bool) -> dict[str, int | str]:
    db = SessionLocal()
    report: dict[str, int | str] = {
        "mode": "apply" if apply else "dry-run",
        "project_files": 0,
        "company_files": 0,
        "company_media": 0,
        "meeting_attachments": 0,
        "missing_files": 0,
    }
    try:
        for model, counter in (
            (CompanyOnboardingSource, "company_files"),
            (CompanyMediaAsset, "company_media"),
        ):
            rows = db.query(model).filter(model.storage_path.isnot(None), model.is_encrypted.is_(False)).all()
            for row in rows:
                path = company_storage.resolve_company_file(row.storage_path)
                if not path.is_file():
                    report["missing_files"] += 1
                    continue
                report[counter] += 1
                if apply:
                    row.content_hash, row.encryption_key_id = company_storage.encrypt_legacy_company_file(row.storage_path)
                    row.is_encrypted = True
                    db.commit()

        project_sources = db.query(ProjectOnboardingSource).filter(
            ProjectOnboardingSource.storage_path.isnot(None),
            ProjectOnboardingSource.is_encrypted.is_(False),
        ).all()
        for source in project_sources:
            path = project_storage.resolve_project_file(source.storage_path)
            if not path.is_file():
                report["missing_files"] += 1
                continue
            report["project_files"] += 1
            if apply:
                source.content_hash, source.encryption_key_id = project_storage.encrypt_legacy_project_file(source.storage_path)
                source.is_encrypted = True
                db.commit()

        attachments = db.query(MeetingAttachment).filter(
            MeetingAttachment.is_encrypted.is_(False),
        ).all()
        for attachment in attachments:
            path = meeting_storage.resolve_meeting_attachment(attachment.storage_path)
            if not path.is_file():
                report["missing_files"] += 1
                continue
            report["meeting_attachments"] += 1
            if apply:
                attachment.content_hash, attachment.encryption_key_id = meeting_storage.encrypt_legacy_meeting_attachment(
                    attachment.storage_path,
                )
                attachment.is_encrypted = True
                db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Encrypt files; otherwise only report pending work.")
    args = parser.parse_args()
    report = encrypt_existing_materials(apply=args.apply)
    print("Material encryption report")
    for key, value in report.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
