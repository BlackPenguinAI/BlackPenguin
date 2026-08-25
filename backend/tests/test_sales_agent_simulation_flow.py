import asyncio
from datetime import datetime
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.db.base  # noqa: F401 - register all models
from app.db.postgres import Base
from app.modules.ai_core.models import AIConfiguration
from app.modules.companies.models import Company
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects.models import Project, ProjectCampaign, ProjectProfile, ProjectPropertyType, ProjectUnit
from app.modules.sales_agent.models import SalesAgentSimulation, SalesFollowUpJob, SalesMessage
from app.modules.sales_agent.schemas import SimulationLeadForm
from app.modules.sales_agent.service import simulate_turn
from app.modules.sales_agent.simulation_service import (
    advance_simulation,
    confirm_simulation_appointment,
    create_simulation,
    generate_initial_message,
    simulation_options,
    slots_for_simulation,
)
from app.modules.sales_crm.models import Lead, Meeting, SalesAvailabilityWindow
from app.modules.users.models import User, UserRole


LLM_REPLY = (
    '{"reply":"Hi, this is Black Penguin following up about your home search. '
    'What is your preferred number of bedrooms?","intent":"qualification",'
    '"extracted_facts":[],"proposed_actions":[{"type":"ask_qualification_question"}],'
    '"requires_human":false,"reason":"Need one preference"}'
)

SLOTS_REPLY = (
    '{"reply":"I will check the available appointment slots. Please hold on.",'
    '"intent":"appointment_request","extracted_facts":[],'
    '"proposed_actions":[{"type":"request_available_slots"}],'
    '"requires_human":false,"reason":"Check verified availability"}'
)


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _fixture(db):
    company = Company(name="Tenant A")
    other = Company(name="Tenant B")
    db.add_all([company, other]); db.flush()
    admin = User(company_id=company.id, email="admin@tenant.test", hashed_password="x", role=UserRole.ADMIN)
    sales_a = User(company_id=company.id, email="sales-a@tenant.test", hashed_password="x", role=UserRole.SALES, first_name="Ava")
    sales_b = User(company_id=company.id, email="sales-b@tenant.test", hashed_password="x", role=UserRole.SALES, first_name="Ben")
    db.add_all([admin, sales_a, sales_b]); db.flush()
    project = Project(company_id=company.id, name="Approved Project", onboarding_status="completed")
    db.add(project); db.flush()
    profile = ProjectProfile(project_id=project.id, final_approved=True, profile_data={"short_description": "Homes"}, field_states={"short_description": {"status": "confirmed"}})
    campaign = ProjectCampaign(project_id=project.id, name="Meta Family Campaign", status="draft")
    product = ProjectPropertyType(
        project_id=project.id, name="Oxford F", code="OXF", bedrooms=4, bathrooms=3.5,
        area_min=2774, area_max=3000, area_unit="ft²", total_units=7, available_units=1,
        starting_price=589990, maximum_price=650000, currency="USD", review_status="confirmed",
        inventory_updated_at=datetime(2026, 8, 14, 12, 0),
    )
    db.add_all([profile, campaign, product]); db.flush()
    for user in (sales_a, sales_b):
        db.add(ProjectUserAssignment(project_id=project.id, user_id=user.id, responsibility="sales", is_active=True, accepts_new_leads=True))
        for weekday in range(7):
            db.add(SalesAvailabilityWindow(user_id=user.id, weekday=weekday, start_time="00:00", end_time="23:59", timezone="UTC"))
    db.add(AIConfiguration(company_id=company.id, openrouter_api_key="test", agent_ventas={
        "model": "test/model", "system_prompt": "Sell only this Project.",
        "protocol_prompt": "Ask one question.", "guardrails_prompt": "Never cross tenants.",
    }))
    db.commit()
    return company, other, admin, sales_a, sales_b, project, campaign, product


def _lead_form(product, suffix="1"):
    return {
        "first_name": "Lead", "last_name": suffix, "phone": f"+1555000000{suffix}",
        "email": f"lead{suffix}@example.test", "product_id": f"property_type:{product.id}",
        "budget_min": 600000, "budget_max": 700000, "consent": True, "custom_answers": {},
    }


def _create(db, company, admin, project, campaign, product, suffix="1"):
    return create_simulation(
        db,
        company_id=company.id,
        created_by_user_id=admin.id,
        project_id=project.id,
        campaign_id=campaign.id,
        lead_form=_lead_form(product, suffix),
    )


def _start(db, company, admin, project, campaign, product, suffix="1"):
    created = _create(db, company, admin, project, campaign, product, suffix)
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)):
        generated = asyncio.run(generate_initial_message(
            db, company_id=company.id, simulation_id=created["simulation_id"],
        ))
    return {**created, "initial_reply": generated.get("reply")}


def test_completed_project_meta_form_starts_an_isolated_sms_simulation():
    db = _db(); company, other, admin, _, _, project, campaign, product = _fixture(db)
    options = simulation_options(db, company_id=company.id)
    assert options[0]["id"] == project.id
    assert options[0]["campaigns"][0]["id"] == campaign.id
    assert options[0]["products"][0]["id"] == f"property_type:{product.id}"
    assert options[0]["products"][0]["starting_price"] == 589990
    assert options[0]["eligible_sales_users"] == 2

    result = _start(db, company, admin, project, campaign, product)
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    messages = db.query(SalesMessage).filter_by(conversation_id=simulation.conversation_id).all()
    assert result["initial_reply"].startswith("Hi")
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert simulation.prompt_snapshot["guardrails_prompt"] == "Never cross tenants."

    with pytest.raises(HTTPException) as captured:
        slots_for_simulation(db, company_id=other.id, simulation_id=simulation.id)
    assert captured.value.status_code == 404


def test_lead_is_saved_before_the_first_llm_call_and_keeps_structured_product_context():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    result = _create(db, company, admin, project, campaign, product)
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    lead = db.query(Lead).filter_by(id=result["lead_id"]).one()
    assert result["status"] == "initializing"
    assert result["requires_initial_message"] is True
    assert db.query(SalesMessage).filter_by(conversation_id=simulation.conversation_id).count() == 0
    assert lead.full_name == "Lead 1"
    qualification = __import__("json").loads(lead.qualification_summary)
    assert qualification["selected_product"]["id"] == f"property_type:{product.id}"
    assert qualification["budget"] == {"minimum": 600000.0, "maximum": 700000.0, "currency": "USD"}
    assert "purchase_timeline" not in qualification
    assert simulation.form_snapshot["selected_product"]["inventory_updated_at"] == "2026-08-14T12:00:00"
    json.dumps(simulation.form_snapshot)


def test_initial_sms_is_idempotent_and_rejects_cross_tenant_access():
    db = _db(); company, other, admin, _, _, project, campaign, product = _fixture(db)
    result = _create(db, company, admin, project, campaign, product)
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)) as llm:
        first = asyncio.run(generate_initial_message(db, company_id=company.id, simulation_id=result["simulation_id"]))
        second = asyncio.run(generate_initial_message(db, company_id=company.id, simulation_id=result["simulation_id"]))
    assert first["run_id"] == second["run_id"]
    assert llm.await_count == 1
    assert db.query(SalesMessage).filter_by(conversation_id=result["conversation_id"]).count() == 1
    with pytest.raises(HTTPException) as captured:
        asyncio.run(generate_initial_message(db, company_id=other.id, simulation_id=result["simulation_id"]))
    assert captured.value.status_code == 404


def test_simulation_rejects_a_property_type_from_another_project():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    other_project = Project(company_id=company.id, name="Other", onboarding_status="completed")
    db.add(other_project); db.flush()
    other_product = ProjectPropertyType(project_id=other_project.id, name="Other product", review_status="confirmed")
    db.add(other_product); db.commit()
    payload = _lead_form(product)
    payload["product_id"] = f"property_type:{other_product.id}"
    with pytest.raises(HTTPException) as captured:
        create_simulation(
            db, company_id=company.id, created_by_user_id=admin.id,
            project_id=project.id, campaign_id=campaign.id, lead_form=payload,
        )
    assert captured.value.status_code == 422


def test_meta_form_requires_contact_product_and_a_valid_budget_range():
    with pytest.raises(ValueError, match="Maximum budget"):
        SimulationLeadForm(
            first_name="Taylor", last_name="Morgan", phone="+13055550142",
            email="taylor@example.com", product_id="property_type:home",
            budget_min=750000, budget_max=600000, consent=True,
        )


def test_demo_project_keeps_product_choices_from_unit_typologies():
    db = _db(); company, _, _, _, _, _, _, _ = _fixture(db)
    demo = Project(company_id=company.id, name="Demo", onboarding_status="completed", is_demo=True)
    db.add(demo); db.flush()
    db.add_all([
        ProjectUnit(project_id=demo.id, unit_code="D-1", typology="Two bedrooms", list_price=610000, currency="USD", status="available"),
        ProjectUnit(project_id=demo.id, unit_code="D-2", typology="Two bedrooms", list_price=650000, currency="USD", status="available"),
    ])
    db.commit()
    option = next(item for item in simulation_options(db, company_id=company.id) if item["id"] == demo.id)
    assert option["products"][0]["id"] == "unit_typology:Two bedrooms"
    assert option["products"][0]["available_units"] == 2


def test_failed_initial_sms_is_recoverable_without_duplicating_messages():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    result = _create(db, company, admin, project, campaign, product)
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(side_effect=RuntimeError("provider timeout"))):
        with pytest.raises(RuntimeError, match="provider timeout"):
            asyncio.run(generate_initial_message(db, company_id=company.id, simulation_id=result["simulation_id"]))
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    assert simulation.status == "needs_retry"
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)):
        recovered = asyncio.run(generate_initial_message(db, company_id=company.id, simulation_id=result["simulation_id"]))
    assert recovered["reply"].startswith("Hi")
    assert db.query(SalesMessage).filter_by(conversation_id=result["conversation_id"]).count() == 1


def test_verified_slots_and_round_robin_create_sales_visible_demo_appointments():
    db = _db(); company, _, admin, sales_a, sales_b, project, campaign, product = _fixture(db)
    first = _start(db, company, admin, project, campaign, product, "1")
    second = _start(db, company, admin, project, campaign, product, "2")
    first_slots = slots_for_simulation(db, company_id=company.id, simulation_id=first["simulation_id"])
    assert first_slots and first_slots[0]["eligible_sales_users"] == 2
    first_meeting = confirm_simulation_appointment(
        db, company_id=company.id, simulation_id=first["simulation_id"],
        starts_at=first_slots[0]["start_at"], duration_minutes=45, modality="virtual",
    )
    second_slots = slots_for_simulation(db, company_id=company.id, simulation_id=second["simulation_id"])
    second_meeting = confirm_simulation_appointment(
        db, company_id=company.id, simulation_id=second["simulation_id"],
        starts_at=second_slots[1]["start_at"], duration_minutes=45, modality="virtual",
    )
    assert {first_meeting["assigned_sales_user_id"], second_meeting["assigned_sales_user_id"]} == {sales_a.id, sales_b.id}
    meetings = db.query(Meeting).order_by(Meeting.created_at).all()
    assert all(item.is_demo and item.source == "agent_simulation" for item in meetings)
    assert all(item.broker_id is None for item in meetings)


def test_virtual_clock_runs_due_follow_up_and_stop_cancels_future_work():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    result = _start(db, company, admin, project, campaign, product)
    assert db.query(SalesFollowUpJob).filter_by(status="pending").count() == 1
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)):
        advanced = asyncio.run(advance_simulation(
            db, company_id=company.id, simulation_id=result["simulation_id"], hours=25,
        ))
    assert advanced["processed_follow_ups"] == 1
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    lead_id = simulation.lead_id
    stop = asyncio.run(simulate_turn(db, company_id=company.id, lead_id=lead_id, inbound_text="STOP"))
    assert stop["intent"] == "opt_out"
    assert db.query(SalesFollowUpJob).filter_by(status="pending").count() == 0


def test_live_reply_after_follow_up_uses_the_monotonic_simulation_clock():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    result = _start(db, company, admin, project, campaign, product)
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)):
        asyncio.run(advance_simulation(
            db, company_id=company.id, simulation_id=result["simulation_id"], hours=25,
        ))
        asyncio.run(simulate_turn(
            db, company_id=company.id, lead_id=result["lead_id"], inbound_text="Yes, tell me more",
        ))
    messages = db.query(SalesMessage).filter_by(
        conversation_id=result["conversation_id"],
    ).order_by(SalesMessage.created_at).all()
    reminder = next(message for message in messages if message.status == "simulated_follow_up_24h")
    later_inbound = next(message for message in messages if message.content == "Yes, tell me more")
    assert later_inbound.created_at > reminder.created_at
    assert messages[-1].role == "assistant"


def test_slot_request_is_executed_and_returns_verified_times_in_the_same_turn():
    db = _db(); company, _, admin, _, _, project, campaign, product = _fixture(db)
    project.timezone = "UTC"
    db.add(project); db.commit()
    result = _start(db, company, admin, project, campaign, product)
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    simulation.virtual_now = datetime(2026, 8, 25, 18, 0)
    db.add(simulation); db.commit()
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=SLOTS_REPLY)):
        response = asyncio.run(simulate_turn(
            db,
            company_id=company.id,
            lead_id=result["lead_id"],
            inbound_text="Monday, the 31st, works for me",
        ))
    assert "verified appointment times" in response["reply"]
    assert "Monday, August 31" in response["reply"]
    assert "hold on" not in response["reply"].lower()


def test_simulation_migration_adopts_existing_schema_and_is_repeatable(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260817_sales_agent_simulation.py"
    spec = importlib.util.spec_from_file_location("agent_simulation_migration", path)
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
        assert {"sales_agent_simulations", "sales_follow_up_jobs", "sales_availability_windows", "calendar_connections"}.issubset(tables)
