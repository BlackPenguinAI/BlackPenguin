import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.core.secret_store import encrypt_secret
from app.db.postgres import Base
from app.integrations.messaging_gateway import company_live_channel
from app.integrations.telnyx_client import send_whatsapp
from app.modules.companies.models import Company
from app.modules.companies.country import sync_project_country
from app.modules.projects.models import Project, ProjectProfile
from app.modules.system_settings.models import TelnyxCompanyConfig, TelnyxConfig
from app.modules.sales_agent.live_service import _whatsapp_customer_window_open
from app.modules.sales_agent.models import SalesConversation, SalesMessage


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _configured(db):
    company = Company(name="Peru Realty", country_code="PE")
    db.add(company); db.flush()
    db.add_all([
        TelnyxConfig(
            api_key_ciphertext=encrypt_secret("KEY-valid"),
            webhook_public_key="c3VzOHVsWUhuY3ZEcjdMeEdxL2lIcUlXNjZUTHBlYnJDeHdJOHhBREhiST0=",
            verification_status="verified", live_sms_enabled=True,
        ),
        TelnyxCompanyConfig(
            company_id=company.id, messaging_profile_id="profile-1",
            primary_channel="whatsapp", whatsapp_business_account_id="waba-1",
            whatsapp_phone_number_id="wa-phone-1", whatsapp_from_phone_number="+51999000111",
            whatsapp_template_name="lead_welcome_es", whatsapp_template_language="es_PE",
            whatsapp_verification_status="verified", live_whatsapp_enabled=True,
        ),
    ])
    db.commit()
    return company


def test_company_primary_channel_does_not_fall_back_to_sms():
    db = _db(); company = _configured(db)
    assert company_live_channel(db, company_id=company.id) == "whatsapp"
    config = db.query(TelnyxCompanyConfig).filter_by(company_id=company.id).one()
    config.live_whatsapp_enabled = False
    db.commit()
    assert company_live_channel(db, company_id=company.id) is None


def test_telnyx_whatsapp_initial_message_uses_company_template():
    db = _db(); company = _configured(db)
    response = httpx.Response(200, json={"data": {"id": "wa-message-1", "status": "queued"}})
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.return_value = response
    with patch("app.integrations.telnyx_client.httpx.AsyncClient", return_value=client):
        result = asyncio.run(send_whatsapp(
            db, company_id=company.id, to="+51999888777", body="Hello",
            use_initial_template=True,
        ))
    assert result["sid"] == "wa-message-1"
    assert client.post.await_args.args[0] == "https://api.telnyx.com/v2/messages/whatsapp"
    request = client.post.await_args.kwargs
    assert request["json"]["from"] == "+51999000111"
    assert request["json"]["whatsapp_message"] == {
        "type": "template",
        "template": {
            "name": "lead_welcome_es",
            "language": {"policy": "deterministic", "code": "es_PE"},
        },
    }


def test_company_country_change_is_inherited_by_existing_projects():
    db = _db()
    company = Company(name="Regional Realty", country_code="US")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project", country="US")
    db.add(project); db.flush()
    profile = ProjectProfile(
        project_id=project.id,
        profile_data={"country": "US"},
        field_states={"country": {"status": "confirmed", "applicable": True}},
    )
    db.add(profile); db.commit()

    sync_project_country(db, company_id=company.id, country_code="PE")
    db.commit(); db.refresh(project); db.refresh(profile)

    assert project.country == "PE"
    assert profile.profile_data["country"] == "PE"
    assert profile.field_states["country"]["status"] == "confirmed"


def test_whatsapp_free_form_window_requires_a_recent_inbound_message():
    db = _db(); company = _configured(db)
    project = Project(company_id=company.id, name="Project", country="PE")
    db.add(project); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id="lead-1",
        channel="whatsapp", provider="telnyx", provider_thread_key="thread-1",
    )
    db.add(conversation); db.flush()
    assert _whatsapp_customer_window_open(db, conversation) is False
    db.add(SalesMessage(
        conversation_id=conversation.id, channel="whatsapp", direction="inbound",
        role="lead", content="Hola", status="received",
    ))
    db.commit()
    assert _whatsapp_customer_window_open(db, conversation) is True
