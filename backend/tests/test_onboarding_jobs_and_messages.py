import ast
import inspect
from unittest.mock import Mock

from app.db.base import Base
from app.db.schema import CURRENT_SCHEMA_VERSION
from app.modules.company_onboarding.models import OnboardingMessage
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_jobs.service import normalize_url
from app.modules.projects import services as project_services
from app.modules.projects.models import ProjectMessage, SenderType


def test_url_normalization_supports_idempotent_jobs():
    assert normalize_url("HTTPS://Example.COM/project/#overview") == "https://example.com/project"
    assert normalize_url("https://example.com/project") == "https://example.com/project"


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
