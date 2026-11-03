"""Issues 1-3: prices, deferred capabilities, draft/published revisions.

Every provider/model interaction is mocked: these tests never send a message.
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa
from app.db.postgres import Base
from app.modules import onboarding_versions as versions
from app.modules.companies.models import Company
from app.modules.company_onboarding import services as companies
from app.modules.company_onboarding.completion import REQUIRED_FIELDS, CONDITIONAL_FIELDS, calculate_completion as company_completion
from app.modules.company_onboarding.models import CompanyProfile, OnboardingSession, OnboardingMessage, SenderType as CompanySender
from app.modules.governance.models import PlatformAuditEvent
from app.modules.money import parse_amount, format_amount
from app.modules.projects import services, catalog_service
from app.modules.projects.completion import FIELDS, calculate_completion
from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType, ProjectSession, ProjectMessage, SenderType
from app.modules.projects.schemas import PropertyTypeCreate
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.live_service import _dispatch
from app.modules.sales_agent.models import AgentRun, SalesConversation, OutboundMessage
from app.modules.sales_agent.monetary_policy import validate_monetary_reply
from app.modules.sales_agent.response_policy import grounded_catalog_reply
from app.modules.sales_crm.models import Lead
from app.modules.users.models import User, UserRole


@pytest.fixture
def context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    company = Company(name="Revision tests", country_code="US")
    db.add(company); db.flush()
    user = User(company_id=company.id, email="admin@revision.test", hashed_password="unused", role=UserRole.ADMIN, is_active=True)
    project = Project(company_id=company.id, name="Approved project", onboarding_status="in_progress")
    db.add_all([user, project]); db.flush()
    states = {f.key: {"status": "not_applicable" if f.requirement == "conditionally_required" else "confirmed", "applicable": f.requirement != "conditionally_required"}
              for f in FIELDS if f.requirement in {"required", "conditionally_required"}}
    profile = ProjectProfile(project=project, profile_data={"project_name": project.name, "starting_price": 30, "currency": "USD", "sales_authorization": True}, field_states=states)
    item = ProjectPropertyType(project=project, name="Residence A", starting_price=30, maximum_price=45.75, currency="USD", review_status="confirmed", available_units=3, inventory_updated_at=datetime(2026, 10, 1))
    db.add_all([profile, item, ProjectSession(project_id=project.id)])
    db.commit()
    services.complete_onboarding(db, project, user.id)
    yield db, company, user, project, profile, item
    db.close(); engine.dispose()


@pytest.mark.parametrize("value,expected", [
    (30,"30"), (30000,"30000"), (Decimal("30.25"),"30.25"),
    ("30000.50","30000.50"), ("30000,50","30000.50"),
    ("30,000.50","30000.50"), ("30.000,50","30000.50"),
    ("30 000,50","30000.50"), ("30\u00a0000.50","30000.50"), (0,"0"),
])
def test_lossless_amounts(value, expected):
    assert parse_amount(value) == Decimal(expected)


@pytest.mark.parametrize("value", [True, False, "NaN", float("inf"), -1, "30,000", "30.000", "1,23,456", "30.005", "USD 30", "30k", 1e100, None])
def test_ambiguous_or_invalid_input_is_not_silently_converted(value):
    with pytest.raises(ValueError):
        parse_amount(value)


def test_explicit_locale_and_display_preserve_magnitude_and_cents():
    assert parse_amount("30,000", locale="en_US") == 30000
    assert parse_amount("30.000", locale="es_ES") == 30000
    assert format_amount(30000) == "30,000"
    assert format_amount(Decimal("30000.25")) == "30,000.25"
    assert format_amount(30) == "30"


def test_property_payload_rejects_ambiguous_price_and_boolean():
    for price in ("30,000", "30.000", True):
        with pytest.raises(ValidationError):
            PropertyTypeCreate(name="Residence", starting_price=price, currency="USD")
    assert PropertyTypeCreate(name="Residence", starting_price="30.000,50", currency="USD").starting_price == 30000.50


@pytest.mark.parametrize("body", ["It starts at $30,000.", "It costs 30000 USD.", "USD 30000 is confirmed.", "It is EUR 30."])
def test_unapproved_amount_or_currency_never_reaches_customer(body):
    facts = {"property_types": [{"id":"a", "property_type":"Residence", "starting_price":30, "currency":"USD"}]}
    reply, evidence = validate_monetary_reply(body, facts)
    assert evidence["replaced"]
    assert "Residence: 30 USD" in reply
    assert "30,000" not in reply
    assert evidence["sources"][0]["id"] == "a"


def test_valid_amounts_and_non_financial_replies_are_not_rewritten():
    commercial = {"property_types": [{"starting_price":30000.25, "currency":"MXN"}]}
    for reply in ("The price is 30,000.25 MXN.", "Would you prefer a larger layout?"):
        assert validate_monetary_reply(reply, commercial)[0] == reply


def test_monetary_fallback_has_no_invented_price_without_approved_records():
    reply, evidence = validate_monetary_reply("It costs USD 1000.", {})
    assert evidence["replaced"]
    assert "confirmed price" in reply
    assert "1000" not in reply


def test_catalog_and_llm_share_the_same_approved_price(context):
    db, company, user, project, profile, item = context
    # The approved structured catalog beats a stale profile minimum, including
    # one already present when the previous release was approved.
    profile.published_snapshot = {**profile.published_snapshot, "data": {**profile.published_snapshot["data"], "starting_price":30000}}
    db.commit()
    commercial = build_commercial_context(db, project=project, company_id=company.id, lead_id="test")
    assert commercial["confirmed_project_facts"]["starting_price"] == 30
    assert commercial["property_types"][0]["starting_price"] == 30
    reply = grounded_catalog_reply("What are the prices?", commercial)
    assert "30 USD" in reply and "30,000" not in reply
    assert validate_monetary_reply("It is $30,000.", commercial)[1]["replaced"]


def test_edit_preserves_published_truth_until_explicit_reapproval(context):
    db, company, user, project, profile, item = context
    old_revision = profile.published_snapshot["revision"]
    old_date = project.onboarding_completed_at
    message = ProjectMessage(session_id=project.session.id, sender=SenderType.USER, content="Original evidence")
    db.add(message); db.commit()
    services.apply_field_updates(db, profile, [services.user_field_update("project_name", "Revised project")], allow_authoritative_statuses=True, actor_user_id=user.id)
    assert not profile.final_approved and versions.active_approved(profile)
    assert project.name == "Approved project"
    assert project.onboarding_completed_at == old_date
    assert profile.profile_data["project_name"] == "Revised project"
    commercial = build_commercial_context(db, project=project, company_id=company.id, lead_id="test")
    assert commercial["confirmed_project_facts"]["project_name"] == "Approved project"
    assert services.serialize_profile(profile)["completion"]["has_pending_changes"]
    services.complete_onboarding(db, project, user.id)
    assert profile.final_approved and project.name == "Revised project"
    assert profile.published_snapshot["revision"] > old_revision
    assert db.get(ProjectMessage, message.id).content == "Original evidence"
    audit = db.query(PlatformAuditEvent).filter(PlatformAuditEvent.event_type == "onboarding.draft_updated").one()
    assert audit.actor_user_id == user.id
    assert audit.payload_json["before"]["data"]["project_name"] == "Approved project"
    assert audit.payload_json["after"]["data"]["project_name"] == "Revised project"


def test_legacy_approval_is_captured_before_edit_without_fabricating_date(context):
    db, company, user, project, profile, item = context
    profile.published_snapshot = None; profile.draft_revision = 0; db.commit()
    services.apply_field_updates(db, profile, [services.user_field_update("project_name", "Next")], allow_authoritative_statuses=True)
    assert profile.published_snapshot["legacy_capture"] is True
    assert profile.published_snapshot["data"]["project_name"] == "Approved project"


def test_catalog_edits_and_removals_remain_draft_and_audited(context):
    db, company, user, project, profile, item = context
    catalog_service.update(db, project, item, {"starting_price":30000.25, "maximum_price":45000.75}, user_id=user.id)
    commercial = build_commercial_context(db, project=project, company_id=company.id, lead_id="test")
    assert commercial["property_types"][0]["starting_price"] == 30
    services.complete_onboarding(db, project, user.id)
    commercial = build_commercial_context(db, project=project, company_id=company.id, lead_id="test")
    assert commercial["property_types"][0]["starting_price"] == 30000.25
    catalog_service.remove(db, project, item)
    assert build_commercial_context(db, project=project, company_id=company.id, lead_id="test")["property_types"]
    with pytest.raises(HTTPException):
        services.complete_onboarding(db, project, user.id)


def test_stale_revision_cannot_overwrite_newer_draft(context):
    db, company, user, project, profile, item = context
    old_revision = profile.draft_revision
    services.apply_field_updates(db, profile, [services.user_field_update("project_name", "First edit")], allow_authoritative_statuses=True, expected_revision=old_revision)
    with pytest.raises(HTTPException) as exc:
        services.apply_field_updates(db, profile, [services.user_field_update("project_name", "Stale edit")], allow_authoritative_statuses=True, expected_revision=old_revision)
    assert exc.value.status_code == 409
    assert profile.profile_data["project_name"] == "First edit"


def test_preview_and_visit_location_do_not_leak_pending_revision(context):
    from app.modules.projects.locations import locations_for_project
    from app.modules.sales_agent.simulation_service import _products, _delivery_timeline
    db, company, user, project, profile, item = context
    # A published version with no delivery confirmation must not obtain a
    # pending delivery claim from the legacy scalar field.
    project.address = "Approved address"
    profile.delivery_dates = "Unapproved delivery claim"
    services.apply_field_updates(db, profile, [services.user_field_update("exact_address", "Draft address")], allow_authoritative_statuses=True, actor_user_id=user.id)
    catalog_service.update(db, project, item, {"starting_price":30000, "maximum_price":45000}, user_id=user.id)
    assert _products(db, project)[0]["starting_price"] == 30
    assert _delivery_timeline(project) is None
    assert locations_for_project(project)[0]["address"] == "Approved address"


def test_rejected_price_keeps_original_text_as_evidence():
    reply = "The property costs 30 USD."
    _, evidence = validate_monetary_reply(reply, {"property_types":[{"starting_price":30000, "currency":"USD"}]})
    assert evidence["original_reply"] == reply


def test_idempotent_approval_and_rejected_updates_do_not_create_audit_noise(context):
    db, company, user, project, profile, item = context
    count = db.query(PlatformAuditEvent).count()
    revision = profile.draft_revision
    services.complete_onboarding(db, project, user.id)
    result = services.apply_field_updates(db, profile, [{"field":"tenant_secret", "status":"confirmed", "value":"x"}], allow_authoritative_statuses=True)
    assert result.rejected and profile.final_approved
    assert profile.draft_revision == revision and db.query(PlatformAuditEvent).count() == count


def test_extraction_cannot_replace_a_confirmed_field_or_grant_permissions(context):
    db, company, user, project, profile, item = context
    result = services.apply_field_updates(db, profile, [{"field":"project_name", "status":"confirmed", "value":"Injected"}], allow_authoritative_statuses=False)
    assert result.rejected and profile.profile_data["project_name"] == "Approved project"
    assert profile.final_approved


def test_manual_messaging_does_not_depend_on_deferred_meta_and_team(context):
    db, company, user, project, profile, item = context
    states = dict(profile.field_states)
    for field in ("campaigns_defined", "meta_connection_verified", "sales_contacts", "appointment_routing"):
        states[field] = {"status":"deferred", "applicable":True}
    summary = calculate_completion(states, final_approved=True)
    assert summary["can_complete"]
    assert summary["capabilities"]["manual_messaging"]["ready"]
    assert not summary["capabilities"]["appointments"]["ready"]
    assert not summary["capabilities"]["meta_lead_ads"]["ready"]
    profile.field_states = states; profile.published_snapshot = None; db.commit()
    versions.require_capability(profile)
    with pytest.raises(HTTPException):
        versions.require_capability(profile, "meta_lead_ads")


def test_deferred_required_fact_and_authorization_are_not_final_approval(context):
    db, company, user, project, profile, item = context
    states = dict(profile.field_states)
    states["starting_price"] = {"status":"deferred", "applicable":True}
    assert not calculate_completion(states)["required_fields_complete"]
    states["sales_authorization"] = {"status":"deferred", "applicable":True}
    assert not calculate_completion(states, final_approved=True)["capabilities"]["manual_messaging"]["ready"]
    profile.field_states = states; profile.published_snapshot = None; db.commit()
    with pytest.raises(HTTPException):
        versions.require_capability(profile)


def test_company_drafts_need_reapproval_but_keep_history(context):
    db, company, user, project, _, item = context
    states = {f.key:{"status":"confirmed", "applicable":True} for f in REQUIRED_FIELDS}
    states.update({f.key:{"status":"not_applicable", "applicable":False} for f in CONDITIONAL_FIELDS})
    profile = CompanyProfile(company_id=company.id, profile_data={"headquarters":"Old address"}, field_states=states)
    session = OnboardingSession(company_id=company.id)
    db.add_all([profile, session]); db.flush()
    msg = OnboardingMessage(session_id=session.id, sender=CompanySender.USER, content="Original Company evidence")
    db.add(msg); db.commit()
    companies.approve_profile(db, profile, actor_user_id=user.id)
    companies.apply_field_updates(db, profile, [{"field":"headquarters", "status":"confirmed", "value":"New address"}], allow_authoritative_statuses=True, actor_user_id=user.id)
    assert not profile.final_approved and versions.active_approved(profile)
    assert profile.published_snapshot["data"]["headquarters"] == "Old address"
    assert companies.serialize_profile(profile)["completion"]["has_pending_changes"]
    companies.approve_profile(db, profile, actor_user_id=user.id)
    assert profile.published_snapshot["data"]["headquarters"] == "New address"
    assert db.get(OnboardingMessage,msg.id).content == "Original Company evidence"
    states[REQUIRED_FIELDS[0].key] = {"status":"deferred"}
    assert not company_completion(states, final_approved=True)["can_complete"]


def test_other_company_cannot_obtain_the_approved_snapshot(context):
    db, company, user, project, profile, item = context
    with pytest.raises(ValueError):
        build_commercial_context(db, project=project, company_id="another-company", lead_id="test")


def test_dispatch_rechecks_price_after_graph_and_persists_exact_sent_content(context):
    db, company, user, project, profile, item = context
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Test lead", phone="+12025550123")
    db.add(lead); db.flush()
    conversation = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id, provider="telnyx", channel="sms", provider_thread_key="test-only")
    db.add(conversation); db.flush()
    run = AgentRun(conversation_id=conversation.id, event_id="test-event", mode="live", status="completed", graph_version="test", toolset_version="test", model="test", prompt_snapshot={}, input_snapshot={}, output_snapshot={})
    db.add(run); db.commit()
    provider = AsyncMock(return_value={"sid":"mock-message", "status":"sent"})
    with patch("app.modules.sales_agent.live_service.send_message", provider), patch("app.modules.sales_agent.live_service.send_sms", provider):
        message = asyncio.run(_dispatch(db, conversation=conversation, lead=lead, content="It costs $30,000.", role="assistant", agent_run_id=run.id))
    assert "Residence A: 30 USD" in provider.call_args.kwargs["body"]
    assert "30,000" not in message.content
    assert db.query(OutboundMessage).one().content == message.content == run.output_snapshot["reply"]
    assert run.output_snapshot["dispatch_monetary_validation"]["replaced"]


def test_named_property_cannot_quote_a_different_propertys_price():
    commercial = {"property_types": [
        {"id":"a", "property_type":"Residence A", "starting_price":30, "currency":"USD"},
        {"id":"b", "property_type":"Residence B", "starting_price":30000, "currency":"USD"},
    ]}
    reply, evidence = validate_monetary_reply("Residence B costs 30 USD.", commercial)
    assert evidence["replaced"]
    assert "Residence B: 30,000 USD" in reply


def test_verified_lead_budget_is_not_misrepresented_as_an_invented_property_price():
    lead_profile = {"facts":{"budget":{"value":{"minimum":100000, "currency":"USD"}}}}
    reply = "Your budget is $100,000. Which layout do you prefer?"
    commercial = {"property_types":[{"starting_price":30000,"currency":"USD"}]}
    assert validate_monetary_reply(reply, commercial, lead_profile=lead_profile)[0] == reply
    assert validate_monetary_reply(reply, commercial)[1]["replaced"]


def test_failed_transaction_keeps_published_version_and_audit_unchanged(context):
    db, company, user, project, profile, item = context
    revision = profile.draft_revision
    count = db.query(PlatformAuditEvent).count()
    services.apply_field_updates(db, profile, [services.user_field_update("project_name", "Aborted")], allow_authoritative_statuses=True, actor_user_id=user.id, commit=False)
    db.rollback(); db.refresh(profile)
    assert profile.final_approved and profile.draft_revision == revision
    assert profile.profile_data["project_name"] == "Approved project"
    assert db.query(PlatformAuditEvent).count() == count


def test_replaying_same_field_value_keeps_approval_and_revision(context):
    db, company, user, project, profile, item = context
    # Same provenance on both attempts must not reopen approval just because
    # source.recorded_at has a new wall clock time.
    update = services.user_field_update("project_name", "Approved project")
    services.apply_field_updates(db, profile, [update], allow_authoritative_statuses=True)
    services.complete_onboarding(db, project, user.id)
    revision = profile.draft_revision
    services.apply_field_updates(db, profile, [update], allow_authoritative_statuses=True)
    assert profile.final_approved and profile.draft_revision == revision


def test_withdrawal_of_ai_permission_is_immediate_even_with_published_profile(context):
    db, company, user, project, profile, item = context
    services.apply_field_updates(db, profile, [services.user_field_update("sales_authorization", False)], allow_authoritative_statuses=True, actor_user_id=user.id)
    with pytest.raises(HTTPException):
        versions.require_capability(profile)
    assert not services.serialize_profile(profile)["completion"]["capabilities"]["manual_messaging"]["ready"]


def test_new_migration_preserves_legacy_profiles_and_has_one_head():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = Path(__file__).resolve().parents[1]
    filename = root / "alembic/versions/20261103_onboarding_versions.py"
    spec = importlib.util.spec_from_file_location("revision_under_test", filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("company_profiles", "project_profiles"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, profile_data TEXT)")
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES ('legacy', 'original evidence')")
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        for table in ("company_profiles", "project_profiles"):
            row = connection.exec_driver_sql(f"SELECT profile_data, published_snapshot, draft_revision FROM {table}").one()
            assert tuple(row) == ("original evidence", None, 0)
    cfg = Config(str(root / "alembic.ini")); cfg.set_main_option("script_location", str(root / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == [module.revision]
