import asyncio
import importlib.util
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
from app.modules.projects.models import Project, ProjectCampaign, ProjectProfile
from app.modules.sales_agent.models import SalesAgentSimulation, SalesFollowUpJob, SalesMessage
from app.modules.sales_agent.service import simulate_turn
from app.modules.sales_agent.simulation_service import (
    advance_simulation,
    confirm_simulation_appointment,
    create_simulation,
    simulation_options,
    slots_for_simulation,
)
from app.modules.sales_crm.models import Meeting, SalesAvailabilityWindow
from app.modules.users.models import User, UserRole


LLM_REPLY = (
    '{"reply":"Hi, this is Black Penguin following up about your home search. '
    'What is your preferred number of bedrooms?","intent":"qualification",'
    '"extracted_facts":[],"proposed_actions":[{"type":"ask_qualification_question"}],'
    '"requires_human":false,"reason":"Need one preference"}'
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
    db.add_all([profile, campaign]); db.flush()
    for user in (sales_a, sales_b):
        db.add(ProjectUserAssignment(project_id=project.id, user_id=user.id, responsibility="sales", is_active=True, accepts_new_leads=True))
        for weekday in range(7):
            db.add(SalesAvailabilityWindow(user_id=user.id, weekday=weekday, start_time="00:00", end_time="23:59", timezone="UTC"))
    db.add(AIConfiguration(company_id=company.id, openrouter_api_key="test", agent_ventas={
        "model": "test/model", "system_prompt": "Sell only this Project.",
        "protocol_prompt": "Ask one question.", "guardrails_prompt": "Never cross tenants.",
    }))
    db.commit()
    return company, other, admin, sales_a, sales_b, project, campaign


def _start(db, company, admin, project, campaign, suffix="1"):
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=LLM_REPLY)):
        return asyncio.run(create_simulation(
            db,
            company_id=company.id,
            created_by_user_id=admin.id,
            project_id=project.id,
            campaign_id=campaign.id,
            lead_form={
                "full_name": f"Lead {suffix}", "phone": f"+1555000000{suffix}",
                "email": None, "product_interest": "Two bedrooms", "budget": "$700k",
                "purchase_timeline": "Six months", "consent": True, "custom_answers": {},
            },
        ))


def test_completed_project_meta_form_starts_an_isolated_sms_simulation():
    db = _db(); company, other, admin, _, _, project, campaign = _fixture(db)
    options = simulation_options(db, company_id=company.id)
    assert options[0]["id"] == project.id
    assert options[0]["campaigns"][0]["id"] == campaign.id
    assert options[0]["eligible_sales_users"] == 2

    result = _start(db, company, admin, project, campaign)
    simulation = db.query(SalesAgentSimulation).filter_by(id=result["simulation_id"]).one()
    messages = db.query(SalesMessage).filter_by(conversation_id=simulation.conversation_id).all()
    assert result["initial_reply"].startswith("Hi")
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert simulation.prompt_snapshot["guardrails_prompt"] == "Never cross tenants."

    with pytest.raises(HTTPException) as captured:
        slots_for_simulation(db, company_id=other.id, simulation_id=simulation.id)
    assert captured.value.status_code == 404


def test_verified_slots_and_round_robin_create_sales_visible_demo_appointments():
    db = _db(); company, _, admin, sales_a, sales_b, project, campaign = _fixture(db)
    first = _start(db, company, admin, project, campaign, "1")
    second = _start(db, company, admin, project, campaign, "2")
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
    db = _db(); company, _, admin, _, _, project, campaign = _fixture(db)
    result = _start(db, company, admin, project, campaign)
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
