from datetime import datetime, timedelta
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.governance.models import (
    AgentOperatingPolicy, AppointmentEmailOutbox, LegalDocumentVersion, Notification, NotificationOutbox,
    PlatformAuditEvent, SalesAssetAccessEvent, UserLegalAcceptance,
)
from app.modules.governance.schemas import DeletePayload, UserStatusPayload
from app.modules.governance.services import (
    assert_company_license, enqueue_appointment_emails, enqueue_notification, escalation_reason,
    next_allowed_proactive_time, process_appointment_email_outbox, process_notification_outbox,
    published_legal_versions, record_legal_acceptance, record_platform_event,
)
from app.modules.users.models import User, UserRole
from app.modules.users.router import delete_platform_user, set_platform_user_status
from app.modules.projects.asset_share_service import record_access
from app.modules.projects.models import Project, ProjectOnboardingSource, ProjectSourceKind, SalesAssetShare
from app.modules.sales_crm.models import Lead, Meeting, MeetingStatus
from app.modules.sales_crm.router import delete_platform_lead


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _tenant(db):
    company = Company(
        name="Governed Company", is_active=True,
        license_start=datetime(2026, 1, 1), license_end=datetime(2027, 1, 1),
    )
    db.add(company); db.flush()
    admin = User(
        company_id=company.id, email="governance-admin@example.com",
        hashed_password="unused", role=UserRole.ADMIN, is_active=True,
    )
    db.add(admin); db.commit()
    return company, admin


def test_license_window_blocks_inactive_future_and_expired_tenants(db):
    company, admin = _tenant(db)
    assert_company_license(db, admin, now=datetime(2026, 6, 1))

    company.license_start = datetime(2026, 7, 1); db.commit()
    with pytest.raises(HTTPException) as future:
        assert_company_license(db, admin, now=datetime(2026, 6, 1))
    assert future.value.detail["code"] == "COMPANY_LICENSE_NOT_STARTED"

    company.license_start = datetime(2025, 1, 1)
    company.license_end = datetime(2026, 6, 1); db.commit()
    with pytest.raises(HTTPException) as expired:
        assert_company_license(db, admin, now=datetime(2026, 6, 1))
    assert expired.value.detail["code"] == "COMPANY_LICENSE_EXPIRED"

    company.is_active = False; company.license_end = None; db.commit()
    with pytest.raises(HTTPException) as suspended:
        assert_company_license(db, admin, now=datetime(2026, 6, 1))
    assert suspended.value.detail["code"] == "COMPANY_SUSPENDED"


def test_superadmin_is_not_bound_to_a_tenant_license(db):
    user = User(
        email="platform-admin@example.com", hashed_password="unused",
        role=UserRole.SUPERADMIN, is_active=True,
    )
    db.add(user); db.commit()
    assert_company_license(db, user, now=datetime(2026, 6, 1))


def test_superadmin_can_suspend_reactivate_and_safely_delete_a_user(db):
    company, _ = _tenant(db)
    superadmin = User(
        email="lifecycle-superadmin@example.com", hashed_password="unused",
        role=UserRole.SUPERADMIN, is_active=True,
    )
    sales = User(
        company_id=company.id, email="sales-to-remove@example.com", hashed_password="unused",
        role=UserRole.SALES, is_active=True,
    )
    db.add_all([superadmin, sales]); db.commit()

    set_platform_user_status(
        sales.id, UserStatusPayload(action="suspend", reason="Security review"),
        None, db, superadmin,
    )
    assert sales.is_active is False
    set_platform_user_status(
        sales.id, UserStatusPayload(action="reactivate", reason="Review completed"),
        None, db, superadmin,
    )
    assert sales.is_active is True

    delete_platform_user(
        sales.id,
        DeletePayload(reason="Employment ended", confirmation="sales-to-remove@example.com"),
        None, False, db, superadmin,
    )
    db.refresh(sales)
    assert sales.deleted_at is not None
    assert sales.is_active is False
    assert sales.firebase_uid is None
    assert sales.email.endswith("@blackpenguin.invalid")


def test_superadmin_lead_deletion_is_tenant_scoped_and_stops_automation(db):
    company, _ = _tenant(db)
    other = Company(name="Other Company", is_active=True)
    superadmin = User(
        email="lead-admin@example.com", hashed_password="unused",
        role=UserRole.SUPERADMIN, is_active=True,
    )
    project = Project(company_id=company.id, name="Governed Project")
    db.add_all([other, superadmin, project]); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Lead To Delete",
        phone="+15550001111", email="lead@example.com", agent_status="active",
    )
    db.add(lead); db.commit()

    with pytest.raises(HTTPException) as cross_tenant:
        delete_platform_lead(
            lead.id, other.id,
            DeletePayload(reason="Deletion request", confirmation="Lead To Delete"),
            None, db, superadmin,
        )
    assert cross_tenant.value.status_code == 404

    delete_platform_lead(
        lead.id, company.id,
        DeletePayload(reason="Deletion request", confirmation="Lead To Delete"),
        None, db, superadmin,
    )
    db.refresh(lead)
    assert lead.deleted_at is not None
    assert lead.agent_status == "deleted"
    assert lead.email is None
    assert lead.full_name == "Deleted lead"


def test_legal_acceptance_is_versioned_and_requires_the_current_snapshot(db):
    _, admin = _tenant(db)
    versions = published_legal_versions(db)
    assert set(versions) == {"privacy", "terms", "data_deletion"}
    with pytest.raises(HTTPException) as changed:
        record_legal_acceptance(
            db, user=admin, invitation_id=None,
            accepted_version_ids={"privacy": "stale"}, request=None,
        )
    assert changed.value.detail["code"] == "LEGAL_DOCUMENT_VERSION_CHANGED"

    acceptance = record_legal_acceptance(
        db, user=admin, invitation_id=None,
        accepted_version_ids={key: value.id for key, value in versions.items()}, request=None,
    )
    db.commit()
    assert db.query(UserLegalAcceptance).filter_by(id=acceptance.id).count() == 1
    assert db.query(LegalDocumentVersion).count() == 3


def test_audit_events_form_a_tamper_evident_hash_chain(db):
    company, admin = _tenant(db)
    first = record_platform_event(
        db, actor=admin, event_type="USER_SUSPENDED", entity_type="user",
        entity_id=admin.id, company_id=company.id, reason="security review",
    )
    second = record_platform_event(
        db, actor=admin, event_type="USER_REACTIVATED", entity_type="user",
        entity_id=admin.id, company_id=company.id, reason="review complete",
    )
    db.commit()
    assert first.event_hash != second.event_hash
    assert second.previous_hash == first.event_hash
    assert db.query(PlatformAuditEvent).count() == 2


def test_operating_windows_return_the_current_or_next_permitted_time(db):
    company, _ = _tenant(db)
    db.add(AgentOperatingPolicy(
        company_id=company.id, timezone="UTC", is_enabled=True,
        weekly_windows={"0": [{"start": "09:00", "end": "17:00"}], "1": [{"start": "10:00", "end": "12:00"}]},
        blackout_dates=["2026-09-14"],
    ))
    db.commit()
    monday = datetime(2026, 9, 14, 14, 0)
    assert next_allowed_proactive_time(
        db, company_id=company.id, project_id=None, now=monday,
    ) == datetime(2026, 9, 15, 10, 0)

    db.query(AgentOperatingPolicy).one().blackout_dates = []
    db.commit()
    assert next_allowed_proactive_time(
        db, company_id=company.id, project_id=None, now=monday,
    ) == monday


@pytest.mark.parametrize(("message", "reason"), [
    ("Quiero hablar con un asesor humano", "HUMAN_REQUESTED"),
    ("Please transfer me to a sales representative", "HUMAN_REQUESTED"),
    ("Necesito asesoría legal sobre una cláusula", "LEGAL_QUESTION"),
    ("Can you negotiate a special discount?", "COMPLEX_NEGOTIATION"),
    ("What apartments are available?", None),
])
def test_escalation_rules_are_deterministic_in_spanish_and_english(message, reason):
    assert escalation_reason(message) == reason


def test_notification_outbox_is_idempotent_and_fans_out_to_tenant_roles(db):
    company, admin = _tenant(db)
    assistant = User(
        company_id=company.id, email="assistant@example.com", hashed_password="unused",
        role=UserRole.ASSISTANT, is_active=True,
    )
    db.add(assistant); db.commit()
    first = enqueue_notification(
        db, company_id=company.id, project_id=None, event_type="appointment_confirmed",
        entity_type="meeting", entity_id="meeting-1",
        payload={"title": "Appointment confirmed", "body": "A lead confirmed."},
        dedupe_key="appointment:meeting-1:confirmed",
    )
    second = enqueue_notification(
        db, company_id=company.id, project_id=None, event_type="appointment_confirmed",
        entity_type="meeting", entity_id="meeting-1", payload={},
        dedupe_key="appointment:meeting-1:confirmed",
    )
    assert first.id == second.id
    assert process_notification_outbox(db, company_id=company.id) == 2
    assert {item.recipient_user_id for item in db.query(Notification).all()} == {admin.id, assistant.id}
    assert process_notification_outbox(db, company_id=company.id) == 0


def test_notification_recipient_roles_exclude_unrequested_tenant_roles(db):
    company, admin = _tenant(db)
    assistant = User(
        company_id=company.id, email="assistant-filter@example.com", hashed_password="unused",
        role=UserRole.ASSISTANT, is_active=True,
    )
    mkt = User(
        company_id=company.id, email="mkt-filter@example.com", hashed_password="unused",
        role=UserRole.MKT, is_active=True,
    )
    db.add_all([assistant, mkt]); db.commit()
    enqueue_notification(
        db, company_id=company.id, project_id=None, event_type="new_lead",
        entity_type="lead", entity_id="lead-1",
        payload={
            "title": "New lead", "body": "A new lead arrived.",
            "recipient_roles": ["admin", "assistant"],
        },
        dedupe_key="new-lead:lead-1",
    )
    assert process_notification_outbox(db, company_id=company.id) == 2
    assert {item.recipient_user_id for item in db.query(Notification).all()} == {admin.id, assistant.id}


def test_appointment_email_outbox_is_idempotent_and_builds_both_messages(db, monkeypatch):
    company, _ = _tenant(db)
    project = Project(
        company_id=company.id, name="Harbor Homes", address="100 Ocean Ave",
        city="Miami", country="USA", timezone="America/New_York",
    )
    sales = User(
        company_id=company.id, email="sales-calendar@example.com", hashed_password="unused",
        first_name="Alex", last_name="Rivera", role=UserRole.SALES, is_active=True,
    )
    db.add_all([project, sales]); db.flush()
    lead = Lead(
        company_id=company.id, project_id=project.id, full_name="Taylor Morgan",
        phone="+15550003333", email="taylor@example.com",
    )
    db.add(lead); db.flush()
    meeting = Meeting(
        project_id=project.id, lead_id=lead.id, assigned_sales_user_id=sales.id,
        meeting_time=datetime(2026, 9, 18, 19, 0), duration_minutes=45,
        status=MeetingStatus.CONFIRMED, confirmation_status="confirmed",
    )
    db.add(meeting); db.flush()

    first = enqueue_appointment_emails(
        db, company_id=company.id, meeting_id=meeting.id,
        lead_email=lead.email, sales_email=sales.email,
    )
    second = enqueue_appointment_emails(
        db, company_id=company.id, meeting_id=meeting.id,
        lead_email=lead.email, sales_email=sales.email,
    )
    db.commit()
    assert {item.id for item in first} == {item.id for item in second}
    assert db.query(AppointmentEmailOutbox).count() == 2

    sent: list[dict] = []
    monkeypatch.setattr(
        "app.modules.governance.services.send_appointment_email",
        lambda **values: sent.append(values),
    )
    assert process_appointment_email_outbox(db) == 2
    assert {item["recipient"] for item in sent} == {lead.email, sales.email}
    assert all("Alex Rivera" in item["body"] for item in sent)
    assert all("100 Ocean Ave" in item["body"] for item in sent)
    assert all("BEGIN:VCALENDAR" in item["ics_content"] for item in sent)
    assert {item.status for item in db.query(AppointmentEmailOutbox).all()} == {"sent"}


def test_shared_material_tracks_successful_human_interest_once_and_ignores_preview_bots(db):
    company, _ = _tenant(db)
    project = Project(company_id=company.id, name="Material Project")
    db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Material Lead", phone="+15550002222")
    source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.IMAGE, name="brochure.png",
    )
    db.add_all([lead, source]); db.flush()
    share = SalesAssetShare(
        company_id=company.id, project_id=project.id, lead_id=lead.id, source_id=source.id,
        token_hash="a" * 64, expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db.add(share); db.commit()

    record_access(
        db, share=share, event_type="view", ip_hash="ip", user_agent_hash="ua-bot",
        user_agent="WhatsApp/preview bot",
    )
    assert share.first_human_access_at is None
    assert db.query(NotificationOutbox).count() == 0

    record_access(
        db, share=share, event_type="view", ip_hash="ip", user_agent_hash="ua-human",
        user_agent="Mozilla/5.0",
    )
    first_access = share.first_human_access_at
    record_access(
        db, share=share, event_type="download", ip_hash="ip", user_agent_hash="ua-human",
        user_agent="Mozilla/5.0",
    )
    assert first_access is not None
    assert share.first_human_access_at == first_access
    assert share.access_count == 3
    assert db.query(SalesAssetAccessEvent).count() == 3
    assert db.query(NotificationOutbox).count() == 1


def test_compliance_migration_is_attached_to_the_current_revision_chain():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260915_compliance_operations.py"
    spec = importlib.util.spec_from_file_location("compliance_operations_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260915_compliance_ops"
    assert migration.down_revision == "20260907_project_receipts"

    calendar_path = Path(__file__).parents[1] / "alembic" / "versions" / "20260917_calendar_email_readiness.py"
    calendar_spec = importlib.util.spec_from_file_location("calendar_email_readiness_migration", calendar_path)
    assert calendar_spec and calendar_spec.loader
    calendar_migration = importlib.util.module_from_spec(calendar_spec)
    calendar_spec.loader.exec_module(calendar_migration)
    assert calendar_migration.revision == "20260917_calendar_email"
    assert calendar_migration.down_revision == migration.revision
