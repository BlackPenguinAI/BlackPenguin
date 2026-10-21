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
from app.integrations.whatsapp_templates import (
    initial_template_parameters,
    render_initial_template,
    validate_initial_template,
)
from app.modules.companies.models import Company
from app.modules.companies.country import sync_project_country
from app.modules.projects.models import Project, ProjectProfile
from app.modules.projects.services import company_messaging_integration
from app.modules.system_settings.models import MessagingRoutingConfig, TelnyxCompanyConfig, TelnyxConfig
from app.modules.sales_agent.live_service import _dispatch, _whatsapp_customer_window_open
from app.modules.sales_agent.graph import PLATFORM_GUARDRAILS
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.services import _whatsapp_template_content


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
            whatsapp_template_name="lead_welcome_en", whatsapp_template_language="en_US",
            whatsapp_template_content="Hi {{1}}, thanks for your interest in {{2}}.",
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


def test_automatic_channel_routes_us_to_sms_and_supported_latam_to_whatsapp_without_fallback():
    db = _db(); company = _configured(db)
    config = db.query(TelnyxCompanyConfig).filter_by(company_id=company.id).one()
    config.primary_channel = "automatic"
    config.from_phone_number = "+13055550142"
    config.verification_status = "verified"
    config.live_sms_enabled = True
    config.regulatory_status = "approved"
    db.add(MessagingRoutingConfig(default_provider="telnyx"))
    db.commit()

    assert company_live_channel(db, company_id=company.id, destination_phone="+13055550999") == "sms"
    assert company_live_channel(db, company_id=company.id, destination_phone="+51999888777") == "whatsapp"
    assert company_live_channel(db, company_id=company.id, destination_phone="+525512345678") == "whatsapp"
    assert company_live_channel(db, company_id=company.id, destination_phone="+541112345678") == "whatsapp"
    assert company_live_channel(db, company_id=company.id, destination_phone="+34911234567") is None

    config.live_sms_enabled = False
    db.commit()
    assert company_live_channel(db, company_id=company.id, destination_phone="+13055550999") is None


def test_project_badge_uses_only_the_owning_company_channel():
    db = _db(); ready_company = _configured(db)
    unconfigured_company = Company(name="Unconfigured Realty", country_code="US")
    db.add(unconfigured_company); db.commit()

    ready = company_messaging_integration(db, ready_company.id)
    missing = company_messaging_integration(db, unconfigured_company.id)

    assert ready["status"] == "connected"
    assert ready["channel"] == "whatsapp"
    assert ready["label"] == "WhatsApp messaging"
    assert missing["status"] == "action_required"
    assert missing["channel"] is None
    assert "this Company's" in missing["detail"]


def test_live_agent_language_is_centralized_in_english():
    assert "Communicate with leads in English only" in PLATFORM_GUARDRAILS


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
            use_initial_template=True, template_parameters=["Taylor", "Project One"],
        ))
    assert result["sid"] == "wa-message-1"
    assert client.post.await_args.args[0] == "https://api.telnyx.com/v2/messages/whatsapp"
    request = client.post.await_args.kwargs
    assert request["json"]["from"] == "+51999000111"
    assert request["json"]["whatsapp_message"] == {
        "type": "template",
        "template": {
            "name": "lead_welcome_en",
            "language": {"policy": "deterministic", "code": "en_US"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "Taylor"},
                    {"type": "text", "text": "Project One"},
                ],
            }],
        },
    }


def test_template_body_is_extracted_for_an_auditable_snapshot():
    assert _whatsapp_template_content({
        "components": [
            {"type": "HEADER", "text": "Header"},
            {"type": "BODY", "text": "The message the lead receives."},
        ],
    }) == "The message the lead receives."


def test_initial_whatsapp_trace_stores_the_rendered_template_not_a_technical_placeholder():
    db = _db(); company = _configured(db)
    project = Project(company_id=company.id, name="Project", country="PE")
    db.add(project); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead", phone="+51999888777",
        source="manual", platform="manual",
    )
    db.add(lead); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="whatsapp", provider="telnyx", provider_thread_key="wa-thread",
    )
    db.add(conversation); db.commit()
    with patch("app.modules.sales_agent.live_service.send_message", new=AsyncMock(
        return_value={"sid": "wa-message-1", "status": "queued"},
    )) as sender:
        message = asyncio.run(_dispatch(
            db, conversation=conversation, lead=lead,
            content="Unused generated English draft", role="assistant", agent_run_id=None,
            metadata={"event_kind": "manual_lead_first_contact"},
        ))
    assert message.content == "Hi Lead, thanks for your interest in Project."
    assert message.metadata_json["delivery_kind"] == "whatsapp_template"
    assert message.metadata_json["generated_draft"] == "Unused generated English draft"
    assert message.metadata_json["template_parameters"] == {
        "lead_first_name": "Lead", "project_name": "Project",
    }
    assert sender.await_args.kwargs["template_parameters"] == ["Lead", "Project"]


def test_initial_template_contract_requires_english_name_and_project_parameters():
    content = "Hi {{1}}, thanks for your interest in {{2}}."
    validate_initial_template(language="en_US", content=content)
    parameters = initial_template_parameters(lead_name="Taylor Morgan", project_name="Project One")
    assert parameters == ["Taylor", "Project One"]
    assert render_initial_template(content, parameters) == "Hi Taylor, thanks for your interest in Project One."


def test_initial_template_contract_rejects_fixed_or_non_english_templates():
    for language, content in (
        ("es_PE", "Hola {{1}}, gracias por tu interés en {{2}}."),
        ("en_US", "Welcome to Black Penguin."),
        ("en_US", "Hi {{1}}, your reference is {{3}}."),
    ):
        try:
            validate_initial_template(language=language, content=content)
        except ValueError:
            pass
        else:
            raise AssertionError("The incompatible template should have been rejected.")


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
