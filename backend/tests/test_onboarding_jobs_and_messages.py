import ast
import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import sqlalchemy as sa

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
from app.modules.projects import source_service as project_source_service
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
    assert CURRENT_SCHEMA_VERSION == "20260814_project_onboarding_ux"


def test_project_onboarding_ux_migration_has_no_accidental_bind_parameters(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260814_project_onboarding_ux.py"
    )
    spec = importlib.util.spec_from_file_location(
        "project_onboarding_ux_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()

    profile_update = next(
        str(statement)
        for statement in statements
        if "UPDATE project_profiles" in str(statement)
    )
    assert "jsonb_build_object" in profile_update
    assert not sa.text(profile_update)._bindparams


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
    company_source = inspect.getsource(company_router._state_payload)
    assert "pending_review" in company_source
    assert "_stage_next_question(stage, profile)" in company_source
    assert company_router._stage_next_question("website_review", None) is None
    assert company_router._stage_next_question("team", None) is None

    project_source = inspect.getsource(project_router._state_payload)
    assert "pending_review" in project_source
    assert "if not processing and not pending_review:" in project_source


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


def test_company_chat_initializes_accepted_updates_before_processing_urls():
    source = inspect.getsource(company_router.send_chat_message)

    assert source.index("accepted = deterministic_result.accepted") < source.index(
        "for url in services.extract_urls"
    )


def test_project_structured_answers_are_resolved_without_an_llm_round_trip(monkeypatch):
    question = ProjectMessage(
        id="question-id",
        session_id="session-id",
        sender=SenderType.AI,
        content="Choose a description",
        ui_payload={
            "field": "short_description",
            "input_type": "long_text",
            "options": [],
            "examples": [],
            "answer_actions": {},
        },
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = question
    monkeypatch.setattr(project_services, "get_active_question", lambda *_args, **_kwargs: question)
    profile = Mock(profile_data={})

    resolution = project_services.resolve_answer_to_question(
        db,
        session_id="session-id",
        message_id="question-id",
        answer="Modern homes with thoughtful layouts, exceptional services, and convenient access to the city.",
        profile=profile,
    )

    assert resolution.handled is True
    assert resolution.status == "accepted"
    assert resolution.updates[0]["field"] == "short_description"
    assert resolution.updates[0]["status"] == "confirmed"


def test_ai_sales_authorization_rejects_free_text_and_requires_the_typed_action(monkeypatch):
    question = ProjectMessage(
        id="authorization-question",
        session_id="session-id",
        sender=SenderType.AI,
        content="Authorize AI-assisted sales",
        ui_payload={
            "field": "sales_authorization",
            "input_type": "ai_sales_authorization",
            "options": [],
            "examples": [],
            "answer_actions": {},
        },
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = question
    monkeypatch.setattr(project_services, "get_active_question", lambda *_args, **_kwargs: question)

    resolution = project_services.resolve_answer_to_question(
        db,
        session_id="session-id",
        message_id=question.id,
        answer="Authorized",
        profile=Mock(profile_data={}),
    )

    assert resolution.status == "rejected"
    assert resolution.reason == "explicit_consent_required"


def test_confirmed_project_name_updates_the_canonical_project_in_the_same_unit_of_work(monkeypatch):
    project = SimpleNamespace(
        name="Untitled Project",
        onboarding_status="draft",
        onboarding_completed_at=None,
        onboarding_approved_by_user_id=None,
    )
    profile = SimpleNamespace(
        project=project,
        profile_data={},
        field_states={},
        field_sources={},
        final_approved=False,
        approved_for_sales_at=None,
        completion_percentage=0,
        is_fully_completed=False,
        sales_activation_status="not_ready",
    )
    db = Mock()
    monkeypatch.setattr(project_services, "flag_modified", lambda *_args: None)

    result = project_services.apply_field_updates(
        db,
        profile,
        [project_services.user_field_update("project_name", " Riverstone Homes ")],
        allow_authoritative_statuses=True,
        commit=False,
    )

    assert result.accepted[0]["field"] == "project_name"
    assert project.name == "Riverstone Homes"
    assert profile.profile_data["project_name"] == "Riverstone Homes"
    assert db.add.call_args_list[0].args[0] is project


def test_project_chat_has_a_bounded_fallback_and_queues_file_extraction():
    completion_source = inspect.getsource(project_router._complete_chat_turn)
    file_chat_source = inspect.getsource(project_router.send_chat_with_files)
    file_upload_source = inspect.getsource(project_router.add_files)
    worker_source = inspect.getsource(job_service._process_project)

    assert "timeout_seconds=20.0" in completion_source
    assert "temporarily unavailable" in completion_source
    assert "create_file_source(" in file_chat_source
    assert "ingest_file(" not in file_chat_source
    assert "job_service.enqueue(" in file_chat_source
    assert "create_file_source(" in file_upload_source
    assert "process_stored_file_source" in worker_source
    assert project_source_service.file_job_url(Mock(project_id="project-id", id="source-id")) \
        == "https://project-files.invalid/project-id/source-id"
