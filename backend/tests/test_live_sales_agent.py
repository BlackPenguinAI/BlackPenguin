from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.base  # noqa: F401 - register every model
from app.core.secret_store import decrypt_secret
from app.db.postgres import Base
from app.integrations.twilio_client import validate_twilio_signature
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project
from app.modules.sales_crm.intelligence import update_lead_intelligence
from app.modules.sales_crm.models import CalendarConnection, Lead, SalesAvailabilityWindow
from app.modules.sales_crm.scheduling import available_slots, next_cadence_time
from app.modules.sales_agent.live_service import ensure_contact, get_or_create_live_conversation
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_agent.service import set_conversation_action
from app.modules.system_settings.models import TwilioConfig
from app.modules.system_settings.schemas import TwilioConfigUpdate
from app.modules.system_settings.services import (
    get_twilio_config,
    twilio_config_response,
    update_twilio_config,
)
from app.modules.users.models import User, UserRole


TEST_ACCOUNT_SID = "AC" + ("1" * 32)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_twilio_token_is_migrated_to_ciphertext_and_never_returned():
    db = _db()
    db.add(TwilioConfig(
        account_sid=TEST_ACCOUNT_SID,
        auth_token="legacy-secret-token",
        from_phone_number="+18573824206",
    ))
    db.commit()
    config = get_twilio_config(db)
    response = twilio_config_response(config)
    assert config.auth_token is None
    assert decrypt_secret(config.auth_token_ciphertext) == "legacy-secret-token"
    assert response["auth_token_configured"] is True
    assert response["auth_token_hint"] == "oken"
    assert "auth_token" not in response


def test_changing_twilio_credentials_forces_reverification_and_normalizes_phone():
    db = _db()
    config = TwilioConfig(
        account_sid=TEST_ACCOUNT_SID,
        auth_token_ciphertext="encrypted-placeholder",
        auth_token_hint="1234",
        from_phone_number="+18573824206",
        live_sms_enabled=True,
        verification_status="verified",
    )
    db.add(config); db.commit()
    updated = update_twilio_config(db, TwilioConfigUpdate(from_phone_number="+1 857 382 4207"))
    assert updated.from_phone_number == "+18573824207"
    assert updated.live_sms_enabled is False
    assert updated.verification_status == "pending"


def test_verified_twilio_configuration_can_be_enabled_without_reverification():
    db = _db()
    config = TwilioConfig(
        account_sid=TEST_ACCOUNT_SID,
        auth_token_ciphertext="encrypted-placeholder",
        auth_token_hint="1234", from_phone_number="+18573824206",
        live_sms_enabled=False, verification_status="verified",
    )
    db.add(config); db.commit()
    updated = update_twilio_config(db, TwilioConfigUpdate(
        account_sid=config.account_sid, from_phone_number="+1 857 382 4206", live_sms_enabled=True,
    ))
    assert updated.live_sms_enabled is True
    assert updated.verification_status == "verified"


def test_twilio_signature_validation_uses_the_public_url_and_sorted_form_fields():
    token = "secret"
    url = "https://blackpenguin.ai/api/v1/webhooks/twilio/sms"
    params = {"From": "+15550000000", "Body": "Hello", "MessageSid": "SM123"}
    payload = url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
    signature = base64.b64encode(
        hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()
    assert validate_twilio_signature(auth_token=token, url=url, params=params, signature=signature)
    assert not validate_twilio_signature(auth_token=token, url=url, params=params, signature="invalid")


def test_lead_intelligence_scores_explicit_context_and_does_not_infer_protected_traits():
    db = _db()
    company = Company(name="Tenant")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project", timezone="America/Bogota")
    db.add(project); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Taylor Morgan",
        phone="+15550000000", email="taylor@example.test", source="meta", platform="meta",
        meta_form_data={"budget": 600000}, consent_status="granted",
    )
    db.add(lead); db.flush()
    update_lead_intelligence(
        db, lead,
        inbound_text="This is my first home; I am pre-approved and want a 2 bedroom next month.",
        conversation_text="I decide alone and have a down payment.", message_count=6,
    )
    db.commit(); db.refresh(lead)
    assert lead.assigned_segment == "first_time_buyer"
    assert lead.intent_tier == "hot"
    serialized = str(lead.meta_form_data).lower()
    assert "gender" not in serialized and "age" not in serialized


def test_slot_scan_fetches_google_busy_ranges_once_per_sales_user():
    db = _db()
    company = Company(name="Tenant")
    db.add(company); db.flush()
    sales = User(company_id=company.id, email="sales@example.test", hashed_password="x", role=UserRole.SALES)
    db.add(sales); db.flush()
    project = Project(company_id=company.id, name="Project", timezone="America/Bogota")
    db.add(project); db.flush()
    db.add(ProjectUserAssignment(project_id=project.id, user_id=sales.id, responsibility="sales", is_active=True, accepts_new_leads=True))
    for weekday in range(7):
        db.add(SalesAvailabilityWindow(user_id=sales.id, weekday=weekday, start_time="08:00", end_time="18:00", timezone="America/Bogota"))
    db.add(CalendarConnection(
        user_id=sales.id, provider="google", calendar_id="primary",
        access_token_ciphertext="encrypted", status="connected",
    ))
    db.commit()
    with patch("app.modules.sales_crm.scheduling.calendar_busy_ranges", return_value=[]) as free_busy:
        slots = available_slots(
            db, project_id=project.id, after=datetime(2026, 8, 31, 12, 0),
            days=2, limit=12,
        )
    assert slots
    assert free_busy.call_count == 1


def test_cadence_is_shifted_into_project_local_contact_hours():
    # 24h after 22:00 UTC is 17:00 in Bogotá, still allowed; a 3h delay
    # lands at 20:00 and must move to 09:00 local the following day.
    scheduled = next_cadence_time(
        now=datetime(2026, 8, 30, 22, 0), timezone_name="America/Bogota", delay_hours=3,
    )
    assert scheduled == datetime(2026, 8, 31, 14, 0)


def test_same_company_phone_history_is_reused_as_one_physical_thread():
    db = _db()
    company = Company(name="Tenant")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project")
    db.add(project); db.flush()
    db.add(TwilioConfig(account_sid=TEST_ACCOUNT_SID, from_phone_number="+18573824206"))
    first = Lead(company_id=company.id, project_id=project.id, full_name="First", phone="+1 (555) 000-0000", source="meta", platform="meta", qualification_summary="Asked about a two-bedroom home.")
    second = Lead(company_id=company.id, project_id=project.id, full_name="Second", phone="+15550000000", source="meta", platform="meta")
    db.add_all([first, second]); db.flush()
    ensure_contact(db, first)
    conversation, created = get_or_create_live_conversation(db, first)
    db.commit()
    assert created is True
    contact = ensure_contact(db, second)
    reused, fresh_lead = get_or_create_live_conversation(db, second)
    db.commit()
    assert fresh_lead is True and reused.id == conversation.id and reused.lead_id == second.id
    assert contact.previous_projects[0]["lead_id"] == first.id


def test_shared_sender_never_reassigns_a_phone_thread_between_companies():
    db = _db()
    first_company = Company(name="Tenant A")
    second_company = Company(name="Tenant B")
    db.add_all([first_company, second_company]); db.flush()
    first_project = Project(company_id=first_company.id, name="A")
    second_project = Project(company_id=second_company.id, name="B")
    db.add_all([first_project, second_project]); db.flush()
    db.add(TwilioConfig(account_sid=TEST_ACCOUNT_SID, from_phone_number="+18573824206"))
    first = Lead(company_id=first_company.id, project_id=first_project.id, full_name="First", phone="+15550000000", source="meta", platform="meta")
    second = Lead(company_id=second_company.id, project_id=second_project.id, full_name="Second", phone="+15550000000", source="meta", platform="meta")
    db.add_all([first, second]); db.flush()
    conversation, _ = get_or_create_live_conversation(db, first)
    db.commit()
    with pytest.raises(HTTPException, match="another Company") as collision:
        get_or_create_live_conversation(db, second)
    assert collision.value.status_code == 409
    assert conversation.company_id == first_company.id
    assert conversation.lead_id == first.id


def test_closed_or_opted_out_live_conversation_cannot_be_resumed():
    db = _db()
    company = Company(name="Tenant")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project")
    db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Lead", phone="+15550000000", source="meta", platform="meta")
    db.add(lead); db.flush()
    conversation = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id, channel="sms", is_paused=True, pause_reason="Appointment confirmed")
    db.add(conversation); db.commit()
    with pytest.raises(HTTPException, match="closed"):
        set_conversation_action(db, company_id=company.id, conversation_id=conversation.id, action="resume")
    conversation.pause_reason = "Lead opted out"; lead.is_opt_out = True; db.commit()
    with pytest.raises(HTTPException, match="opted-out"):
        set_conversation_action(db, company_id=company.id, conversation_id=conversation.id, action="resume")


def test_live_sales_agent_migration_is_repeatable_on_current_schema(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260830_live_sales_agent.py"
    spec = importlib.util.spec_from_file_location("live_sales_agent_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        tables = set(connection.dialect.get_table_names(connection))
    assert {"lead_contacts", "lead_score_snapshots", "prompt_versions"}.issubset(tables)
