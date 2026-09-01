from unittest.mock import patch

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
from app.modules.system_settings.schemas import GoogleCalendarConfigUpdate
from app.modules.system_settings.services import google_calendar_config_response, google_calendar_credentials, update_google_calendar_config


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
