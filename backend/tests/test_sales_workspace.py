from datetime import datetime, timedelta
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

import app.db.base  # noqa: F401 - register every foreign-key target
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_agent.models import SalesConversation, SalesMessage
from app.modules.sales_agent.service import conversation_messages
from app.modules.sales_crm.models import Lead
from app.modules.sales_crm.scheduling import (
    availability_blocks_for_user, create_availability_block, delete_availability_block,
)
from app.modules.sales_crm.services import get_lead_detail
from app.modules.users.models import User, UserRole


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close(); engine.dispose()


def _fixture(db):
    company = Company(name="Tenant", is_active=True)
    sales_a = User(company=company, email="a@example.com", hashed_password="x", role=UserRole.SALES)
    sales_b = User(company=company, email="b@example.com", hashed_password="x", role=UserRole.SALES)
    db.add_all([company, sales_a, sales_b]); db.flush()
    project = Project(company_id=company.id, name="Project", onboarding_status="completed", is_active=True)
    db.add(project); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, assigned_sales_user_id=sales_a.id,
        full_name="Assigned Lead", phone="+15550000000", platform="meta", source="Meta Ads",
        meta_form_data={"budget": "600000", "bedrooms": "3"},
        qualification_summary="The lead wants a three-bedroom home and has confirmed a visit.",
        visit_recommendations="Prepare the three-bedroom floor plans.",
    )
    db.add(lead); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id=lead.id, channel="sms",
    )
    db.add(conversation); db.flush()
    db.add(SalesMessage(
        conversation_id=conversation.id, channel="sms", direction="inbound", role="user",
        content="I prefer three bedrooms.",
    ))
    db.commit()
    return company, sales_a, sales_b, project, lead, conversation


def test_sales_user_manages_date_specific_availability_blocks(db):
    _, sales_a, _, _, _, _ = _fixture(db)
    starts_at = datetime(2026, 8, 28, 14, 0)
    block = create_availability_block(
        db, user=sales_a, starts_at=starts_at, ends_at=starts_at + timedelta(hours=3),
        timezone_name="America/Lima",
    )
    rows = availability_blocks_for_user(
        db, user_id=sales_a.id, starts_at=starts_at, ends_at=starts_at + timedelta(days=1),
    )
    assert [item.id for item in rows] == [block.id]
    with pytest.raises(HTTPException) as error:
        create_availability_block(
            db, user=sales_a, starts_at=starts_at + timedelta(hours=1),
            ends_at=starts_at + timedelta(hours=2), timezone_name="America/Lima",
        )
    assert error.value.status_code == 409
    delete_availability_block(db, user_id=sales_a.id, block_id=block.id)
    assert availability_blocks_for_user(
        db, user_id=sales_a.id, starts_at=starts_at, ends_at=starts_at + timedelta(days=1),
    ) == []


def test_sales_lead_detail_and_chat_are_limited_to_assignee(db):
    company, sales_a, sales_b, _, lead, conversation = _fixture(db)
    detail = get_lead_detail(db, lead.id, company.id, sales_a.id)
    assert detail["meta_form_data"]["bedrooms"] == "3"
    assert detail["conversation_id"] == conversation.id
    assert conversation_messages(
        db, company_id=company.id, conversation_id=conversation.id, sales_user_id=sales_a.id,
    )[0].content == "I prefer three bedrooms."
    with pytest.raises(HTTPException) as detail_error:
        get_lead_detail(db, lead.id, company.id, sales_b.id)
    with pytest.raises(HTTPException) as chat_error:
        conversation_messages(
            db, company_id=company.id, conversation_id=conversation.id, sales_user_id=sales_b.id,
        )
    assert detail_error.value.status_code == 404
    assert chat_error.value.status_code == 404


def test_sales_workspace_migration_creates_availability_table_and_is_repeatable(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260825_sales_workspace.py"
    spec = importlib.util.spec_from_file_location("sales_workspace_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE sales_availability_blocks")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert "sales_availability_blocks" in connection.dialect.get_table_names(connection)
    engine.dispose()
