from datetime import datetime, timedelta
import asyncio
import importlib.util
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi import UploadFile
from starlette.datastructures import Headers
from sqlalchemy import create_engine, inspect
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
from app.modules.sales_crm.models import Lead, Meeting, MeetingAttachment, MeetingStatus
from app.modules.sales_crm.schemas import MeetingUpdate
from app.modules.sales_crm.scheduling import (
    availability_blocks_for_user, create_availability_block, delete_availability_block,
)
from app.modules.sales_crm.router import get_company_sales_schedule, upload_meeting_attachment
from app.modules.sales_crm import storage_service
from app.modules.sales_crm.services import get_lead_detail, update_meeting
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
    assert detail["chat_messages"][0]["content"] == "I prefer three bedrooms."
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


def test_sales_visit_requires_assignee_evidence_and_closing_date(db):
    company, sales_a, sales_b, project, lead, _ = _fixture(db)
    meeting = Meeting(
        project_id=project.id, lead_id=lead.id, assigned_sales_user_id=sales_a.id,
        meeting_time=datetime(2026, 8, 29, 15, 0), status=MeetingStatus.CONFIRMED,
    )
    db.add(meeting); db.commit()
    started = update_meeting(
        db, meeting.id, company.id,
        MeetingUpdate(status=MeetingStatus.IN_PROGRESS, visit_notes="Lead liked the kitchen."), sales_a.id,
    )
    assert started.started_at is not None
    with pytest.raises(HTTPException) as missing_evidence:
        update_meeting(
            db, meeting.id, company.id,
            MeetingUpdate(status=MeetingStatus.SALE_CLOSED, sale_closed_at=datetime(2026, 8, 30)), sales_a.id,
        )
    assert missing_evidence.value.status_code == 422
    assert meeting.completed_at is None
    db.add(MeetingAttachment(
        meeting_id=meeting.id, uploaded_by_user_id=sales_a.id, kind="sale_evidence",
        storage_path="companies/test/evidence.pdf", original_filename="evidence.pdf",
        mime_type="application/pdf", size_bytes=120,
    )); db.commit()
    closed = update_meeting(
        db, meeting.id, company.id,
        MeetingUpdate(
            status=MeetingStatus.SALE_CLOSED, sale_closed_at=datetime(2026, 8, 30),
            visit_details="Contract signed after the visit.",
        ), sales_a.id,
    )
    assert closed.status == MeetingStatus.SALE_CLOSED
    assert closed.completed_at is not None
    assert closed.lead.funnel_stage.value == "closed"
    with pytest.raises(HTTPException) as other_sales:
        update_meeting(db, meeting.id, company.id, MeetingUpdate(visit_notes="Not mine"), sales_b.id)
    assert other_sales.value.status_code == 404


def test_manager_schedule_lists_and_filters_company_sales_users(db):
    company, sales_a, sales_b, project, lead, _ = _fixture(db)
    manager = User(company_id=company.id, email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db.add(manager); db.flush()
    start = datetime(2026, 8, 1)
    create_availability_block(
        db, user=sales_a, starts_at=start + timedelta(days=2, hours=9),
        ends_at=start + timedelta(days=2, hours=12), timezone_name="America/Lima",
    )
    create_availability_block(
        db, user=sales_b, starts_at=start + timedelta(days=3, hours=9),
        ends_at=start + timedelta(days=3, hours=12), timezone_name="America/Toronto",
    )
    db.add_all([
        Meeting(project_id=project.id, lead_id=lead.id, assigned_sales_user_id=sales_a.id, meeting_time=start + timedelta(days=2, hours=10)),
        Meeting(project_id=project.id, lead_id=lead.id, assigned_sales_user_id=sales_b.id, meeting_time=start + timedelta(days=3, hours=10)),
    ]); db.commit()
    all_users = get_company_sales_schedule(start, start + timedelta(days=31), None, db, manager)
    assert {user.id for user in all_users["sales_users"]} == {sales_a.id, sales_b.id}
    assert len(all_users["availability"]) == 2
    assert len(all_users["meetings"]) == 2
    filtered = get_company_sales_schedule(start, start + timedelta(days=31), sales_b.id, db, manager)
    assert {item.user_id for item in filtered["availability"]} == {sales_b.id}
    assert {item.assigned_sales_user_id for item in filtered["meetings"]} == {sales_b.id}


def test_sales_uploads_visit_photo_only_to_assigned_meeting(db, monkeypatch, tmp_path):
    company, sales_a, sales_b, project, lead, _ = _fixture(db)
    meeting = Meeting(
        project_id=project.id, lead_id=lead.id, assigned_sales_user_id=sales_a.id,
        meeting_time=datetime(2026, 8, 29, 15, 0), status=MeetingStatus.IN_PROGRESS,
    )
    db.add(meeting); db.commit()
    monkeypatch.setattr(storage_service.settings, "PROJECT_UPLOAD_ROOT", str(tmp_path))
    upload = UploadFile(
        filename="property.jpg", file=BytesIO(b"safe-image-content"),
        headers=Headers({"content-type": "image/jpeg"}),
    )
    result = asyncio.run(upload_meeting_attachment(meeting.id, "visit_photo", upload, db, sales_a))
    assert result.kind == "visit_photo"
    attachment = db.query(MeetingAttachment).filter(MeetingAttachment.id == result.id).one()
    assert storage_service.resolve_meeting_attachment(attachment.storage_path).read_bytes() == b"safe-image-content"
    denied_upload = UploadFile(
        filename="other.jpg", file=BytesIO(b"other"), headers=Headers({"content-type": "image/jpeg"}),
    )
    with pytest.raises(HTTPException) as denied:
        asyncio.run(upload_meeting_attachment(meeting.id, "visit_photo", denied_upload, db, sales_b))
    assert denied.value.status_code == 404


def test_visit_reporting_migration_is_repeatable(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260825_sales_visit_reporting.py"
    spec = importlib.util.spec_from_file_location("sales_visit_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.NEW_STATUSES == ("IN_PROGRESS", "COMPLETED_SALE_PENDING", "SALE_CLOSED")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE meeting_attachments")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade(); migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("meetings")}
        assert {"visit_notes", "visit_details", "sale_closed_at"}.issubset(columns)
        assert "meeting_attachments" in connection.dialect.get_table_names(connection)
    engine.dispose()


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
