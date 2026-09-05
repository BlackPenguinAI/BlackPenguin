import inspect
from types import SimpleNamespace

from app.modules.onboarding_jobs.continuation import _result_content
from app.modules.company_onboarding import router as company_router
from app.modules.company_onboarding import source_service as company_sources
from app.modules.projects import router as project_router
from app.modules.projects import source_service as project_sources


def _source(name: str, status: str, error: str | None = None):
    return SimpleNamespace(
        name=name,
        status=SimpleNamespace(value=status),
        error_message=error,
    )


def test_all_failed_sources_continue_with_the_next_question():
    content = _result_content(
        [
            _source("protected.pdf", "failed", "The file is password-protected."),
            _source("scanned.pdf", "failed", "No readable text was found."),
        ],
        pending_count=0,
        question_prompt="What is the project type?",
    )

    assert "**protected.pdf:**" in content
    assert "**scanned.pdf:**" in content
    assert "upload accessible copies" in content
    assert "Let's continue: What is the project type?" in content


def test_mixed_group_reports_failures_and_waits_for_review():
    content = _result_content(
        [
            _source("protected.pdf", "failed", "The file is password-protected."),
            _source("brochure.pdf", "ready"),
        ],
        pending_count=4,
        question_prompt="What is the project type?",
    )

    assert "**protected.pdf:**" in content
    assert "4 proposals" in content
    assert "Review them before we continue." in content
    assert "What is the project type?" not in content


def test_exclusive_media_step_can_finish_source_processing_without_empty_connector():
    content = _result_content(
        [_source("example.com", "ready")],
        pending_count=0,
        question_prompt="",
    )

    assert content == "I finished processing 1 accessible source."
    assert "Let's continue:" not in content


def test_project_url_sent_with_files_uses_the_worker():
    source = inspect.getsource(project_router.send_chat_with_files)

    assert "source_service.ingest_url" not in source
    assert "source_service.create_url_source" in source
    assert "job_service.enqueue" in source
    assert 'scope="project"' in source


def test_file_upload_endpoints_finalize_the_group():
    company_source = inspect.getsource(company_router.add_file_sources)
    project_source = inspect.getsource(project_router.add_files)

    assert "message_id=user_message.id" in company_source
    assert "finalize_source_group(" in company_source
    assert "message_id=user_message.id" in project_source
    assert "job_service.enqueue(" in project_source
    assert 'if not any(source.status.value == "processing"' in project_source
    assert "finalize_source_group(" in project_source


def test_protected_files_are_stored_before_analysis():
    for create_file_source in (company_sources.ingest_file, project_sources.create_file_source):
        source = inspect.getsource(create_file_source)
        assert source.index("storage_service.store_") < source.index("_validate_signature(")
