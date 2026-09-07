from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.integrations.gcalendar_client import authorization_url
from app.modules.ai_core.services import (
    create_prompt_draft, prompt_version, prompt_versions, publish_prompt_version,
)
from app.modules.sales_agent.default_prompt import SALES_AGENT_DEFAULT_CONFIG
from app.modules.seo.service import run_audit
from app.modules.system_settings.schemas import GoogleCalendarConfigUpdate, MetaPlatformConfigUpdate
from app.modules.system_settings.services import (
    google_calendar_config_response, google_calendar_credentials, meta_platform_config_response,
    meta_platform_credentials, update_google_calendar_config, update_meta_platform_config,
    verify_meta_platform_config,
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_google_calendar_secret_is_write_only_and_runtime_uses_database_configuration():
    db = _db()
    config = update_google_calendar_config(db, GoogleCalendarConfigUpdate(client_id="calendar-client.apps.googleusercontent.com", client_secret="google-secret-value", redirect_uri="https://blackpenguin.ai/api/v1/sales/calendar/google/callback", is_enabled=True))
    response = google_calendar_config_response(config)
    assert response["client_secret_configured"] is True
    assert response["client_secret_hint"] == "alue"
    assert "client_secret" not in response
    _, secret = google_calendar_credentials(db)
    assert secret == "google-secret-value"
    url = authorization_url(db, "signed-state", "sales@example.com")
    assert "calendar.events" in url and "calendar.freebusy" in url
    assert "calendar.readonly" not in url


def test_meta_platform_secret_is_write_only_and_must_be_verified_before_enabling():
    db = _db()
    config = update_meta_platform_config(db, MetaPlatformConfigUpdate(
        app_id="123456789", app_secret="meta-secret-value", login_config_id="987654321",
        graph_api_version="v23.0",
        redirect_uri="https://blackpenguin.ai/api/v1/projects/integrations/meta/oauth/callback",
        webhook_callback_url="https://blackpenguin.ai/api/v1/webhooks/meta",
    ))
    response = meta_platform_config_response(config)
    assert response["app_secret_configured"] is True
    assert response["app_secret_hint"] == "alue"
    assert "app_secret" not in response

    class MetaResponse:
        def raise_for_status(self): return None
        def json(self): return {"id": "123456789", "name": "Black Penguin"}

    with patch("app.modules.system_settings.services.httpx.get", return_value=MetaResponse()):
        verify_meta_platform_config(db)
    enabled = update_meta_platform_config(db, MetaPlatformConfigUpdate(is_enabled=True))
    assert enabled.is_enabled is True
    _, secret = meta_platform_credentials(db)
    assert secret == "meta-secret-value"


def test_project_chat_message_serializes_persistent_media_evidence():
    from app.modules.projects.models import SenderType
    from app.modules.projects.services import save_message, serialize_message

    db = _db()
    evidence = {"kind": "project_cover", "asset_id": "asset-1", "name": "cover.jpg", "image_url": "/media/asset-1"}
    message = save_message(db, "session-1", SenderType.AI, "Project cover saved.", media_evidence=evidence)
    assert serialize_message(message)["media_evidence"] == evidence


def test_project_chat_message_serializes_structured_artifact_receipt():
    from app.modules.projects.models import SenderType
    from app.modules.projects.services import save_message, serialize_message

    db = _db()
    artifact = {"kind": "property_catalog_snapshot", "confirmed_at": "2026-09-07T00:00:00", "items": [{"name": "Harbor"}]}
    message = save_message(db, "session-1", SenderType.AI, "Catalog saved.", artifact_payload=artifact)
    assert serialize_message(message)["artifact_payload"] == artifact


def test_meta_oauth_state_is_short_lived_hashed_and_bound_to_the_company_project():
    from app.modules.companies.models import Company
    from app.modules.projects.meta_oauth_service import start_oauth
    from app.modules.projects.models import Project
    from app.modules.system_settings.models import MetaOAuthAttempt, MetaPlatformConfig
    from app.modules.users.models import User, UserRole

    db = _db()
    company = Company(name="OAuth Company")
    db.add(company); db.flush()
    user = User(company_id=company.id, first_name="Ana", email="ana-oauth@example.com", hashed_password="x", role=UserRole.ADMIN)
    project = Project(company_id=company.id, name="OAuth Project")
    db.add_all([user, project]); db.commit()
    update_meta_platform_config(db, MetaPlatformConfigUpdate(
        app_id="123456789", app_secret="meta-secret-value", login_config_id="987654321",
        graph_api_version="v23.0", redirect_uri="https://blackpenguin.ai/api/v1/projects/integrations/meta/oauth/callback",
        webhook_callback_url="https://blackpenguin.ai/api/v1/webhooks/meta",
    ))
    config = db.query(MetaPlatformConfig).one()
    config.verification_status = "verified"; config.is_enabled = True; db.commit()

    result = start_oauth(db, project=project, user=user)
    state = parse_qs(urlparse(result["authorization_url"]).query)["state"][0]
    attempt = db.query(MetaOAuthAttempt).one()
    assert attempt.nonce_hash == hashlib.sha256(state.encode()).hexdigest()
    assert state not in attempt.nonce_hash
    assert attempt.company_id == company.id and attempt.project_id == project.id and attempt.user_id == user.id


def test_project_meta_setup_explains_why_oauth_is_unavailable_and_when_it_is_ready():
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project
    from app.modules.projects.router import get_meta_setup_configuration
    from app.modules.system_settings.models import MetaPlatformConfig
    from app.modules.users.models import User, UserRole

    db = _db()
    company = Company(name="Meta Status Company")
    db.add(company); db.flush()
    user = User(company_id=company.id, email="meta-status@example.com", hashed_password="x", role=UserRole.ADMIN)
    project = Project(company_id=company.id, name="Meta Status Project")
    db.add_all([user, project]); db.commit()

    unavailable = get_meta_setup_configuration(project.id, db, user)
    assert unavailable["oauth_enabled"] is False
    assert unavailable["oauth_blocker_code"] == "META_OAUTH_INCOMPLETE"

    update_meta_platform_config(db, MetaPlatformConfigUpdate(
        app_id="123456789", app_secret="meta-secret-value", login_config_id="987654321",
        graph_api_version="v23.0", redirect_uri="https://blackpenguin.ai/api/v1/projects/integrations/meta/oauth/callback",
        webhook_callback_url="https://blackpenguin.ai/api/v1/webhooks/meta",
    ))
    pending = get_meta_setup_configuration(project.id, db, user)
    assert pending["oauth_status"] == "pending_verification"

    config = db.query(MetaPlatformConfig).one()
    config.verification_status = "verified"; config.is_enabled = True; db.commit()
    ready = get_meta_setup_configuration(project.id, db, user)
    assert ready["oauth_enabled"] is True
    assert ready["can_connect"] is True
    assert ready["oauth_blocker_message"] is None


def test_sales_prompt_draft_does_not_change_runtime_until_published():
    db = _db()
    configuration = dict(SALES_AGENT_DEFAULT_CONFIG)
    configuration["system_prompt"] = "Published only after explicit approval."
    draft = create_prompt_draft(db, company_id=None, agent_key="sales", configuration=configuration, change_note="Controlled release", actor_id="actor")
    assert draft.is_published is False
    active = publish_prompt_version(db, company_id=None, agent_key="sales", version_id=draft.id, actor_id="actor")
    assert active.agent_ventas["system_prompt"] == "Published only after explicit approval."
    assert draft.is_published is True


def test_sales_prompt_history_is_paginated_and_details_are_loaded_separately():
    db = _db()
    for number in range(25):
        configuration = dict(SALES_AGENT_DEFAULT_CONFIG)
        configuration["system_prompt"] = f"Version {number + 1}"
        create_prompt_draft(
            db, company_id=None, agent_key="sales", configuration=configuration,
            change_note=f"Change {number + 1}", actor_id="actor",
        )
    first_page, total = prompt_versions(
        db, company_id=None, agent_key="sales", offset=0, limit=20,
    )
    second_page, _ = prompt_versions(
        db, company_id=None, agent_key="sales", offset=20, limit=20,
    )
    detail = prompt_version(
        db, company_id=None, agent_key="sales", version_id=first_page[0].id,
    )
    assert total == 25
    assert len(first_page) == 20
    assert len(second_page) == 5
    assert detail.configuration["system_prompt"] == "Version 25"


class _Response:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text; self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("unexpected response")


def test_seo_audit_persists_repeatable_technical_checks():
    db = _db()
    html = """<html lang="en"><head><title>Black Penguin autonomous real estate platform</title><meta name="description" content="A sufficiently descriptive explanation of the Black Penguin real estate automation platform."><link rel="canonical" href="https://blackpenguin.ai/"><meta property="og:title" content="Black Penguin"><script type="application/ld+json">{}</script></head></html>"""
    with patch("app.modules.seo.service.httpx.get", side_effect=[_Response(html), _Response("User-agent: *"), _Response("<urlset/>\n")]):
        audit = run_audit(db)
    assert audit.status == "healthy"
    assert audit.score == 100
    assert all(audit.details.values())
