from app.modules.company_onboarding.models import OnboardingMessage
from app.modules.onboarding_jobs.service import normalize_url
from app.modules.projects.models import ProjectMessage


def test_url_normalization_supports_idempotent_jobs():
    assert normalize_url("HTTPS://Example.COM/project/#overview") == "https://example.com/project"
    assert normalize_url("https://example.com/project") == "https://example.com/project"


def test_company_messages_persist_visual_question_and_reply_state():
    assert "ui_payload" in OnboardingMessage.__table__.columns
    assert "response_payload" in OnboardingMessage.__table__.columns
    assert "in_reply_to_message_id" in OnboardingMessage.__table__.columns


def test_project_messages_persist_visual_question_and_reply_state():
    assert "ui_payload" in ProjectMessage.__table__.columns
    assert "response_payload" in ProjectMessage.__table__.columns
    assert "in_reply_to_message_id" in ProjectMessage.__table__.columns
