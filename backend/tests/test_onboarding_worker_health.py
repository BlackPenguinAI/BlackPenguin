from __future__ import annotations

import asyncio
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, Mock

from app.modules.onboarding_jobs import service
from app.modules.onboarding_jobs.healthcheck import is_heartbeat_fresh, write_heartbeat


def test_worker_entrypoint_loads_complete_model_registry():
    """Validate mapper initialization in a clean Python interpreter.

    Running this check in the pytest process could hide a missing worker import,
    because another test may already have imported the complete model registry.
    """
    backend_root = Path(__file__).resolve().parents[1]
    required_tables = {
        "subscription_plans",
        "companies",
        "users",
        "company_onboarding_sources",
        "projects",
        "project_onboarding_sources",
        "onboarding_source_jobs",
    }
    script = f"""
from sqlalchemy.orm import configure_mappers

import app.modules.onboarding_jobs.worker
from app.db.postgres import Base

configure_mappers()

required = {required_tables!r}
missing = sorted(required.difference(Base.metadata.tables))
if missing:
    raise SystemExit(f"Missing model tables: {{missing}}")
"""
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        os.pathsep.join((str(backend_root), existing_pythonpath))
        if existing_pythonpath
        else str(backend_root)
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        "The onboarding worker could not initialize the complete SQLAlchemy "
        f"model registry.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_heartbeat_is_fresh_only_inside_allowed_window(tmp_path: Path):
    heartbeat = tmp_path / "worker.heartbeat"
    write_heartbeat(heartbeat)
    modified_at = heartbeat.stat().st_mtime

    assert is_heartbeat_fresh(heartbeat, max_age_seconds=15, now=modified_at + 10)
    assert not is_heartbeat_fresh(heartbeat, max_age_seconds=15, now=modified_at + 16)
    assert not is_heartbeat_fresh(tmp_path / "missing", max_age_seconds=15)


def test_successful_iteration_updates_heartbeat(monkeypatch, tmp_path: Path):
    heartbeat = tmp_path / "worker.heartbeat"
    monkeypatch.setattr(service, "run_once", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "write_heartbeat", lambda: write_heartbeat(heartbeat))

    assert asyncio.run(service.run_iteration()) is False
    assert heartbeat.exists()


def test_failed_iteration_does_not_update_heartbeat(monkeypatch, tmp_path: Path):
    heartbeat = tmp_path / "worker.heartbeat"
    monkeypatch.setattr(
        service,
        "run_once",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(service, "write_heartbeat", lambda: write_heartbeat(heartbeat))

    try:
        asyncio.run(service.run_iteration())
    except RuntimeError as exc:
        assert str(exc) == "database unavailable"
    else:
        raise AssertionError("The failed iteration must propagate its exception")
    assert not heartbeat.exists()


def test_job_failure_is_requeued_with_backoff(monkeypatch):
    job = Mock(
        id="job-id",
        scope="company",
        company_id="company-id",
        project_id=None,
        source_id="source-id",
        attempts=1,
        completed_at=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    monkeypatch.setattr(
        service,
        "_process_company",
        AsyncMock(side_effect=RuntimeError("temporary failure")),
    )

    before = datetime.utcnow()
    asyncio.run(service._process(db, job))

    assert job.status == "queued"
    assert job.available_at > before
    assert job.completed_at is None
    db.commit.assert_called()


def test_job_failure_becomes_terminal_after_max_attempts(monkeypatch):
    job = Mock(
        id="job-id",
        scope="project",
        company_id="company-id",
        project_id="project-id",
        source_id="source-id",
        attempts=service.MAX_ATTEMPTS,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    mark_failed = Mock()
    save_message = Mock()
    monkeypatch.setattr(
        service,
        "_process_project",
        AsyncMock(side_effect=RuntimeError("permanent failure")),
    )
    monkeypatch.setattr(service, "_mark_source_failed", mark_failed)
    monkeypatch.setattr(service, "_save_terminal_failure_message", save_message)

    asyncio.run(service._process(db, job))

    assert job.status == "failed"
    assert isinstance(job.completed_at, datetime)
    mark_failed.assert_called_once_with(db, job)
    save_message.assert_called_once_with(db, job)


def test_company_and_project_jobs_complete(monkeypatch):
    db = MagicMock()
    company_job = Mock(
        id="company-job", scope="company", source_id="source-a", attempts=1,
    )
    project_job = Mock(
        id="project-job", scope="project", source_id="source-b", attempts=1,
    )
    company = AsyncMock(return_value=None)
    project = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "_process_company", company)
    monkeypatch.setattr(service, "_process_project", project)

    asyncio.run(service._process(db, company_job))
    asyncio.run(service._process(db, project_job))

    assert company_job.status == "completed"
    assert project_job.status == "completed"
    company.assert_awaited_once_with(db, company_job)
    project.assert_awaited_once_with(db, project_job)


def test_terminal_failure_marks_company_source_and_adds_message(monkeypatch):
    job = Mock(
        id="job-id",
        scope="company",
        company_id="company-id",
        project_id=None,
        source_id="source-id",
        message_id="origin-message-id",
        error_code="ValueError",
    )
    db = MagicMock()
    source = Mock(error_message=None)
    query = db.query.return_value
    query.filter.return_value.first.return_value = source

    finalize = Mock()
    monkeypatch.setattr(service, "finalize_source_group", finalize)

    service._mark_source_failed(db, job)
    service._save_terminal_failure_message(db, job)

    assert source.status.value == "failed"
    assert "several attempts" in source.error_message
    finalize.assert_called_once_with(
        db,
        scope="company",
        company_id="company-id",
        project_id=None,
        message_id="origin-message-id",
    )


def test_error_details_redact_urls_and_tokens():
    value = service._safe_error_detail(
        "GET https://example.com/private Bearer secret-token sk-or-v1-abcdef"
    )

    assert "https://" not in value
    assert "secret-token" not in value
    assert "abcdef" not in value
