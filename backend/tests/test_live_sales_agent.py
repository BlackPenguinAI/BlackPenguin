from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import importlib.util
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock
import asyncio

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
from app.modules.governance.models import HumanInterventionCase
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project
from app.modules.sales_crm.intelligence import merge_extracted_facts, update_lead_intelligence
from app.modules.sales_crm.models import CalendarConnection, Lead, SalesAvailabilityWindow
from app.modules.sales_crm.scheduling import available_slots, next_cadence_time
from app.modules.sales_agent.default_prompt import merge_sales_agent_defaults
from app.modules.sales_agent.live_service import (
    ensure_contact, get_or_create_live_conversation, process_live_inbound,
    process_live_inbound_job,
)
from app.modules.sales_agent.models import SalesConversation, SalesInboundJob, SalesMessage
from app.modules.sales_agent.live_worker import _claim_inbound_jobs
from app.modules.sales_agent.service import (
    _requested_period, conversation_summaries,
    set_conversation_action,
)
from app.modules.system_settings.models import TwilioConfig
from app.modules.system_settings.schemas import TwilioConfigUpdate
from app.modules.system_settings.services import (
    get_twilio_config,
    twilio_config_response,
    update_twilio_config,
)
from app.modules.users.models import User, UserRole
from zoneinfo import ZoneInfo


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


def test_appointment_intent_advances_stage_and_contributes_to_score():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project", timezone="America/Chicago")
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Taylor Morgan",
        phone="+13055550000", email="taylor@example.test", source="manual", platform="manual",
    )
    db.add_all([project, lead]); db.flush()
    update_lead_intelligence(
        db, lead, inbound_text="Can I schedule a tour on Friday?",
        conversation_text="Can I schedule a tour on Friday?", message_count=2,
    )
    db.flush()
    assert lead.pipeline_stage == "S08_APPOINTMENT"
    assert lead.intent_tier in {"warm", "hot"}


def test_requested_period_handles_weekdays_and_month_ranges_in_project_timezone():
    now = datetime(2026, 10, 1, 15, 0)
    zone = ZoneInfo("America/Chicago")
    assert _requested_period("What do you have Friday?", now=now, zone=zone) == (
        datetime(2026, 10, 2).date(), datetime(2026, 10, 2).date(),
    )
    assert _requested_period("Between October 10 and 20", now=now, zone=zone) == (
        datetime(2026, 10, 10).date(), datetime(2026, 10, 20).date(),
    )
    assert _requested_period("October 30 through November 2", now=now, zone=zone) == (
        datetime(2026, 10, 30).date(), datetime(2026, 11, 2).date(),
    )


def test_legacy_prompt_pack_is_normalized_to_runtime_stage_ids_and_english():
    merged = merge_sales_agent_defaults({
        "model": "test/model",
        "system_prompt": "Use the lead's language and be concise.",
        "protocol_prompt": "Protocol",
        "guardrails_prompt": "Guardrails",
        "stage_prompts": {"S01_CAPTURE": "Capture", "S10_HANDOFF": "Handoff"},
    })
    assert merged["system_prompt"].startswith("Communicate with leads in English only")
    assert merged["stage_prompts"]["S00_CAPTURE"] == "Capture"
    assert merged["stage_prompts"]["S09_HANDOFF"] == "Handoff"
    assert "S10_HANDOFF" not in merged["stage_prompts"]


def test_durable_inbound_job_records_success_and_terminal_failure():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project")
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead",
        phone="+13055550000", source="manual", platform="manual",
    )
    db.add_all([project, lead]); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="sms", provider="telnyx", provider_thread_key="thread",
    )
    db.add(conversation); db.flush()
    message = SalesMessage(
        conversation_id=conversation.id, channel="sms", direction="inbound",
        role="user", content="Friday?", status="received", metadata_json={},
    )
    db.add(message); db.flush()
    job = SalesInboundJob(
        conversation_id=conversation.id, message_id=message.id,
        status="processing", attempt_number=1,
    )
    db.add(job); db.commit()
    job_id, message_id, lead_id = job.id, message.id, lead.id
    with patch("app.modules.sales_agent.live_service.SessionLocal", return_value=db), patch(
        "app.modules.sales_agent.live_service.process_live_inbound", new=AsyncMock(return_value=None),
    ):
        asyncio.run(process_live_inbound_job(job_id))
    job = db.query(SalesInboundJob).filter_by(id=job_id).one()
    message = db.query(SalesMessage).filter_by(id=message_id).one()
    assert job.status == "processed"
    assert message.metadata_json["agent_turn_status"] == "processed"

    job.status = "processing"; job.attempt_number = 3; job.processed_at = None; db.commit()
    with patch("app.modules.sales_agent.live_service.SessionLocal", return_value=db), patch(
        "app.modules.sales_agent.live_service.process_live_inbound",
        new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
    ), pytest.raises(RuntimeError):
        asyncio.run(process_live_inbound_job(job_id))
    job = db.query(SalesInboundJob).filter_by(id=job_id).one()
    lead = db.query(Lead).filter_by(id=lead_id).one()
    assert job.status == "failed"
    assert job.error_message == "Agent turn processing failed. Retry is available."
    assert lead.agent_status == "attention_required"


def test_inbound_job_migration_is_repeatable_on_current_schema(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20261001_sales_inbound_jobs.py"
    spec = importlib.util.spec_from_file_location("sales_inbound_job_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite://"); Base.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade(); migration.upgrade()
        tables = set(connection.dialect.get_table_names(connection))
        columns = {
            item["name"] for item in connection.dialect.get_columns(connection, "sales_inbound_jobs")
        }
    assert "sales_inbound_jobs" in tables
    assert {"conversation_id", "message_id", "status", "attempt_number", "scheduled_at"}.issubset(columns)


def test_live_appointment_request_uses_deterministic_slots_without_calling_the_model():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(
        company_id=company.id, name="Project", address="100 Main Street",
        timezone="America/Chicago",
    )
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead",
        phone="+13055550000", source="manual", platform="manual", consent_status="granted",
    )
    db.add_all([project, lead]); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="sms", provider="telnyx", provider_thread_key="deterministic-thread", is_paused=False,
    )
    db.add(conversation); db.flush()
    message = SalesMessage(
        conversation_id=conversation.id, channel="sms", direction="inbound", role="user",
        content="What appointment times are available?", provider_message_id="inbound-1", status="received",
    )
    db.add(message); db.commit()
    conversation_id, message_id, lead_id = conversation.id, message.id, lead.id
    slot = datetime(2026, 10, 2, 15, 0)
    with patch("app.modules.sales_agent.live_service.SessionLocal", return_value=db), patch(
        "app.modules.sales_agent.live_service.build_sales_graph",
    ) as graph, patch(
        "app.modules.sales_agent.service.available_slots",
        return_value=[{"start_at": slot, "end_at": slot + timedelta(minutes=45), "eligible_sales_users": 1}],
    ), patch(
        "app.modules.sales_agent.live_service._dispatch", new=AsyncMock(return_value=SalesMessage()),
    ) as dispatch:
        asyncio.run(process_live_inbound(conversation_id, message_id))
    graph.assert_not_called()
    assert "verified appointment times" in dispatch.await_args.kwargs["content"]
    lead = db.query(Lead).filter_by(id=lead_id).one()
    assert lead.pipeline_stage == "S08_APPOINTMENT"


def test_inbound_worker_claims_fifo_and_only_one_turn_per_conversation():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project"); db.add(project); db.flush()
    leads = [
        Lead(company_id=company.id, project_id=project.id, full_name=f"Lead {index}", phone=f"+1305555000{index}", source="manual", platform="manual")
        for index in range(2)
    ]
    db.add_all(leads); db.flush()
    conversations = [
        SalesConversation(
            company_id=company.id, project_id=project.id, lead_id=lead.id,
            channel="sms", provider="telnyx", provider_thread_key=f"fifo-{index}", is_paused=False,
        )
        for index, lead in enumerate(leads)
    ]
    db.add_all(conversations); db.flush()
    created = datetime(2026, 10, 1, 12, 0)
    messages = [
        SalesMessage(
            conversation_id=conversation_id, channel="sms", direction="inbound", role="user",
            content=f"Message {index}", provider_message_id=f"fifo-message-{index}",
            created_at=created + timedelta(seconds=index),
        )
        for index, conversation_id in enumerate((conversations[0].id, conversations[0].id, conversations[1].id))
    ]
    db.add_all(messages); db.flush()
    jobs = [
        SalesInboundJob(
            conversation_id=message.conversation_id, message_id=message.id, status="pending",
            scheduled_at=created, created_at=message.created_at,
        )
        for message in messages
    ]
    db.add_all(jobs); db.commit()
    expected = {jobs[0].id, jobs[2].id}
    with patch("app.modules.sales_agent.live_worker.SessionLocal", return_value=db):
        claimed = set(_claim_inbound_jobs(limit=10))
    assert claimed == expected


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


def test_resuming_live_whatsapp_closes_intervention_without_marking_simulation():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project", timezone="America/Lima")
    db.add(project); db.flush()
    user = User(company_id=company.id, email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead", phone="+51999888777",
        source="Manual registration", platform="manual", agent_status="human_control",
    )
    db.add_all([user, lead]); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="whatsapp", provider="telnyx", provider_thread_key="wa-thread",
        is_paused=True, pause_reason="Human intervention: POLICY_VIOLATION",
    )
    db.add(conversation); db.flush()
    intervention = HumanInterventionCase(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        conversation_id=conversation.id, reason="POLICY_VIOLATION",
        status="open", dedupe_key="POLICY_VIOLATION:open",
    )
    db.add(intervention); db.commit()

    set_conversation_action(
        db, company_id=company.id, conversation_id=conversation.id,
        action="resume", actor_user_id=user.id,
    )

    db.refresh(lead); db.refresh(intervention); db.refresh(conversation)
    assert conversation.is_paused is False
    assert lead.agent_status == "active"
    assert intervention.status == "resolved"
    assert intervention.resolved_by_user_id == user.id


def test_agent_facts_update_a_source_aware_progressive_profile():
    lead = Lead(
        company_id="company", project_id="project", full_name="Lead", phone="+51999888777",
        source="Manual registration", platform="manual", lead_profile_data={},
    )
    profile = merge_extracted_facts(lead, [
        {"key": "budget_min", "value": 400000},
        {"field": "property_type", "value": "40 Villa model home"},
        {"key": "internal_instruction", "value": "must be ignored"},
    ], evidence="My budget starts at 400000 and I prefer the 40 Villa.")
    assert profile["facts"]["budget_minimum"]["value"] == 400000
    assert profile["facts"]["budget_minimum"]["source"] == "agent_conversation"
    assert profile["facts"]["property_interest"]["confirmed"] is True
    assert "internal_instruction" not in profile["facts"]
    assert "Minimum budget" in lead.qualification_summary


def test_conversation_summary_exposes_progressive_profile_to_operations_ui():
    db = _db()
    company = Company(name="Tenant"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Project"); db.add(project); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Progressive Lead",
        phone="+51999888777", source="Manual registration", platform="manual",
        qualification_summary="Minimum budget: 400000",
        lead_profile_data={"schema_version": 1, "facts": {"budget_minimum": {"value": 400000}}},
    )
    db.add(lead); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id,
        channel="whatsapp", provider="telnyx", provider_thread_key="profile-thread",
    )
    db.add(conversation); db.commit()

    summary = conversation_summaries(db, company_id=company.id)[0]

    assert summary["qualification_summary"] == "Minimum budget: 400000"
    assert summary["lead_profile_data"]["facts"]["budget_minimum"]["value"] == 400000


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
