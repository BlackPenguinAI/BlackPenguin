import ast
import inspect
from unittest.mock import Mock

from app.db.base import Base
from app.db.schema import CURRENT_SCHEMA_VERSION
from app.modules.company_onboarding.models import OnboardingMessage
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_jobs.service import _compatible_idempotency_keys, normalize_url
from app.modules.onboarding_jobs import service as job_service
from app.modules.onboarding_jobs import continuation as source_continuation
from app.modules.onboarding_jobs.errors import AccessRestrictedError
from app.modules.company_onboarding import router as company_router
from app.modules.projects import router as project_router
from app.modules.projects import services as project_services
from app.modules.projects.models import ProjectMessage, SenderType


def test_url_normalization_supports_idempotent_jobs():
    assert normalize_url("HTTPS://Example.COM/project/#overview") == "https://example.com/project"
    assert normalize_url("https://example.com/project") == "https://example.com/project"
    assert normalize_url("http://www.example.com/?utm_source=chat") == "https://example.com/"
    assert len(_compatible_idempotency_keys(
        scope="company", company_id="company-1", url="https://www.minto.com/", session_id="session-1",
    )) >= 4


def test_repeating_a_failed_url_does_not_implicitly_retry_it():
    failed_job = Mock(status="failed")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = failed_job

    returned = job_service.enqueue(
        db,
        scope="company",
        company_id="company-1",
        source_id="new-source",
        url="https://www.minto.com/",
        session_id="session-1",
    )

    assert returned is failed_job
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_create_all_metadata_registers_durable_jobs_and_schema_version():
    assert OnboardingSourceJob.__tablename__ in Base.metadata.tables
    assert "schema_versions" in Base.metadata.tables
    assert CURRENT_SCHEMA_VERSION == "20260805_onboarding_jobs_v2"


def test_jobs_include_retry_availability_timestamp():
    assert "available_at" in OnboardingSourceJob.__table__.columns


def test_company_messages_persist_visual_question_and_reply_state():
    assert "ui_payload" in OnboardingMessage.__table__.columns
    assert "response_payload" in OnboardingMessage.__table__.columns
    assert "in_reply_to_message_id" in OnboardingMessage.__table__.columns


def test_project_messages_persist_visual_question_and_reply_state():
    assert "ui_payload" in ProjectMessage.__table__.columns
    assert "response_payload" in ProjectMessage.__table__.columns
    assert "in_reply_to_message_id" in ProjectMessage.__table__.columns


def test_project_save_message_supports_atomic_job_creation():
    module_tree = ast.parse(inspect.getsource(project_services))
    definitions = [
        node
        for node in module_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "save_message"
    ]
    assert len(definitions) == 1

    parameters = inspect.signature(project_services.save_message).parameters
    assert {"ui_payload", "in_reply_to_message_id", "commit"} <= parameters.keys()

    db = Mock()
    message = project_services.save_message(
        db,
        session_id="project-session-id",
        sender=SenderType.USER,
        content="https://example.com/project",
        ui_payload={"kind": "source"},
        in_reply_to_message_id="question-message-id",
        commit=False,
    )

    assert message.ui_payload == {"kind": "source"}
    assert message.in_reply_to_message_id == "question-message-id"
    db.add.assert_called_once_with(message)
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()


def test_worker_defers_next_question_when_extracted_proposals_need_review():
    process_source = inspect.getsource(job_service._process)
    continuation_source = inspect.getsource(source_continuation.finalize_source_group)

    assert 'job.status = "completed"' in process_source
    assert "finalize_source_group(" in process_source
    assert 'OnboardingSourceJob.status.in_(["queued", "processing"])' in continuation_source
    assert 'any(_source_value(source, "status") == "processing"' in continuation_source
    assert "pending_count" in continuation_source
    assert "ui_payload = None if pending_count else question" in continuation_source


def test_state_does_not_attach_a_question_while_review_is_pending():
    for state_builder in (company_router._state_payload, project_router._state_payload):
        function_source = inspect.getsource(state_builder)
        assert "pending_review" in function_source
        assert "if not processing and not pending_review:" in function_source


def test_last_proposal_decision_uses_an_idempotent_follow_up():
    for continuation in (
        company_router._continue_after_source_review,
        project_router._continue_after_source_review,
    ):
        function_source = inspect.getsource(continuation)
        assert "finalize_source_group(" in function_source

    function_source = inspect.getsource(source_continuation.finalize_source_group)
    assert ".with_for_update()" in function_source
    assert "in_reply_to_message_id == origin.id" in function_source
    assert "response_payload.is_(None)" in function_source
    assert "commit=False" in function_source


def test_access_restrictions_are_terminal_and_do_not_publish_an_action_payload():
    process_source = inspect.getsource(job_service._process)
    terminal_message_source = inspect.getsource(job_service._save_terminal_failure_message)
    mark_failed_source = inspect.getsource(job_service._mark_source_failed)

    assert "isinstance(exc, AccessRestrictedError)" in process_source
    assert 'job.status = "failed" if non_retryable' in process_source
    assert "ui_payload" not in terminal_message_source
    assert "if not source.error_message" in mark_failed_source
    assert AccessRestrictedError.code == "access_restricted"
