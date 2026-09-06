from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.companies.models import Company
from app.modules.company_onboarding.completion import FIELD_BY_KEY as COMPANY_FIELDS
from app.modules.company_onboarding.models import CompanyMediaAsset, CompanyProfile, OnboardingMessage
from app.modules.company_onboarding.overview_service import _contact_list
from app.modules.company_onboarding.router import select_company_logo
from app.modules.projects import catalog_service
from app.modules.projects.completion import FIELD_BY_KEY as PROJECT_FIELDS, calculate_completion
from app.modules.projects.schemas import PropertyTypeCreate
from app.modules.projects.models import (
    Project, ProjectMessage, ProjectProfile, ProjectPropertyType, ProjectSession, SenderType,
)
from app.modules.projects.router import confirm_property_type_catalog
from app.modules.subscriptions.schemas import PlanCreate
from app.modules.subscriptions.models import SubscriptionPlan
from app.modules.users.models import User, UserAuthStatus, UserRole


def test_catalog_and_media_tables_are_registered():
    assert "company_media_assets" in Base.metadata.tables
    assert "project_property_types" in Base.metadata.tables
    assert "project_property_type_media" in Base.metadata.tables
    assert "sales_asset_shares" in Base.metadata.tables


def test_project_cover_and_structured_catalog_block_completion_until_resolved():
    completion = calculate_completion({}, final_approved=False)
    blocker_keys = {item["field"] for item in completion["blockers"]}
    assert "project_cover" in blocker_keys
    assert "property_type_catalog" in blocker_keys
    assert PROJECT_FIELDS["project_cover"].requirement == "required"


def test_company_logo_is_recommended_and_can_be_deferred():
    assert COMPANY_FIELDS["company_logo"].requirement == "recommended"


def test_selecting_company_logo_records_one_idempotent_confirmation():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        plan = SubscriptionPlan(name="Logo Test", is_active=True)
        company = Company(name="Logo Company", plan=plan, is_active=True)
        db.add_all([plan, company]); db.flush()
        administrator = User(
            company_id=company.id, email="admin@logo.example", first_name="Admin",
            last_name="User", role=UserRole.ADMIN, hashed_password="unused",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        asset = CompanyMediaAsset(
            company_id=company.id, uploaded_by_user_id=None, role="logo_candidate",
            name="logo.png", mime_type="image/png", size_bytes=2048,
            sha256="a" * 64, storage_path="companies/logo.png",
        )
        db.add_all([administrator, asset]); db.commit(); db.refresh(administrator); db.refresh(asset)

        selected = select_company_logo(asset.id, db, administrator)
        select_company_logo(asset.id, db, administrator)

        profile = db.query(CompanyProfile).filter_by(company_id=company.id).one()
        confirmations = db.query(OnboardingMessage).filter(
            OnboardingMessage.content == "I saved the selected image as the official Company logo.",
        ).all()
        assert selected["is_primary"] is True
        assert profile.profile_data["company_logo"] == asset.id
        assert len(confirmations) == 1
    finally:
        db.close(); engine.dispose()


def test_company_overview_contacts_are_split_into_individual_rows():
    assert _contact_list(["info@example.com, sales@example.com", "info@example.com"]) == [
        "info@example.com", "sales@example.com",
    ]
    assert _contact_list("+1 305 555 0100; +51 999 555 010") == [
        "+1 305 555 0100", "+51 999 555 010",
    ]


def test_confirmed_property_type_requires_commercial_freshness():
    item = ProjectPropertyType(
        project_id="project-1", name="Two bedrooms", review_status="confirmed",
        available_units=4, starting_price=Decimal("350000"), currency="USD",
        inventory_updated_at=datetime.utcnow(),
    )
    assert catalog_service.is_complete(item) is True
    item.inventory_updated_at = None
    assert catalog_service.is_complete(item) is False


def test_property_type_confirmation_reports_the_exact_invalid_fields():
    item = ProjectPropertyType(
        project_id="project-1", name="Four bedrooms", review_status="confirmed",
        available_units=2, total_units=1, starting_price=Decimal("20"),
        maximum_price=Decimal("10"), currency="", inventory_updated_at=None,
    )

    assert catalog_service.confirmation_field_errors(item) == {
        "available_units": "Available units cannot exceed total units.",
        "maximum_price": "Maximum price must be greater than or equal to starting price.",
        "currency": "Select the commercial currency.",
        "inventory_updated_at": "Select the inventory update date.",
    }


def test_property_type_payload_normalizes_utc_datetime_for_naive_database_columns():
    payload = PropertyTypeCreate(
        name="Oxford F", available_units=1, total_units=7,
        starting_price=1200, maximum_price=1300, currency="USD",
        inventory_updated_at="2026-08-14T12:00:00.000Z",
    )

    assert payload.inventory_updated_at == datetime(2026, 8, 14, 12, 0)
    assert payload.inventory_updated_at.tzinfo is None


def test_latest_inventory_update_accepts_mixed_legacy_and_timezone_aware_values():
    first = ProjectPropertyType(
        project_id="project-1", name="First", review_status="confirmed",
        inventory_updated_at=datetime(2026, 8, 13, 9, 0),
    )
    second = ProjectPropertyType(
        project_id="project-1", name="Oxford F", review_status="confirmed",
        inventory_updated_at=datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )

    latest = catalog_service._latest_inventory_update([first, second])

    assert latest == datetime(2026, 8, 14, 12, 0)
    assert latest.tzinfo is None


def test_duplicate_property_type_name_returns_a_structured_conflict():
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import pytest
    from fastapi import HTTPException

    db = MagicMock()
    db.no_autoflush = nullcontext()
    db.query.return_value.filter.return_value.first.return_value = object()
    project = SimpleNamespace(id="project-1")
    item = ProjectPropertyType(project_id="project-1", name=" Oxford F ", review_status="confirmed")

    with pytest.raises(HTTPException) as error:
        catalog_service._validate_unique_name(db, project, item)

    assert item.name == "Oxford F"
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "duplicate_property_type_name"
    assert "name" in error.value.detail["field_errors"]


def test_removing_an_extracted_property_candidate_hides_it_without_deleting_audit_history():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        plan = SubscriptionPlan(name="Catalog Test", is_active=True)
        company = Company(name="Catalog Company", plan=plan, is_active=True)
        db.add_all([plan, company]); db.flush()
        project = Project(company_id=company.id, name="Catalog Project")
        profile = ProjectProfile(project=project, profile_data={}, field_states={}, field_sources={})
        candidate = ProjectPropertyType(
            project=project, name="Bayside Collection", review_status="candidate",
            source_reference="https://example.com/property",
        )
        db.add_all([project, profile, candidate]); db.commit(); db.refresh(candidate)

        catalog_service.remove(db, project, candidate)

        hidden = catalog_service.catalog(db, project)
        persisted = db.query(ProjectPropertyType).filter_by(id=candidate.id).one()
        assert hidden["items"] == []
        assert hidden["candidate_count"] == 0
        assert persisted.review_status == "rejected"
    finally:
        db.close(); engine.dispose()


def test_manual_property_can_restore_a_previously_rejected_candidate():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        plan = SubscriptionPlan(name="Restore Test", is_active=True)
        company = Company(name="Restore Company", plan=plan, is_active=True)
        db.add_all([plan, company]); db.flush()
        project = Project(company_id=company.id, name="Restore Project")
        profile = ProjectProfile(project=project, profile_data={}, field_states={}, field_sources={})
        rejected = ProjectPropertyType(project=project, name="Bayside Collection", review_status="rejected")
        db.add_all([project, profile, rejected]); db.commit(); db.refresh(rejected)

        restored = catalog_service.create(db, project, {
            "name": "Bayside Collection", "review_status": "confirmed",
            "available_units": 3, "starting_price": Decimal("450000"),
            "currency": "USD", "inventory_updated_at": datetime.utcnow(),
        }, user_id="user-1")

        assert restored.id == rejected.id
        assert restored.review_status == "confirmed"
        assert catalog_service.catalog(db, project)["confirmed_count"] == 1
    finally:
        db.close(); engine.dispose()


def test_confirming_property_catalog_persists_summary_and_next_question_in_chat():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        plan = SubscriptionPlan(name="Catalog Trace Test", is_active=True)
        company = Company(name="Trace Company", plan=plan, is_active=True)
        db.add_all([plan, company]); db.flush()
        administrator = User(
            company_id=company.id, email="admin@trace.example", first_name="Admin",
            last_name="User", role=UserRole.ADMIN, hashed_password="unused",
            auth_status=UserAuthStatus.ACTIVE, is_active=True,
        )
        project = Project(company_id=company.id, name="Trace Project")
        profile = ProjectProfile(project=project, profile_data={}, field_states={}, field_sources={})
        session = ProjectSession(project=project)
        property_type = ProjectPropertyType(
            project=project, name="Typology 1", review_status="confirmed",
            available_units=10, starting_price=Decimal("50000"), currency="USD",
            inventory_updated_at=datetime.utcnow(),
        )
        question = ProjectMessage(
            session=session, sender=SenderType.AI, content="Review the Property catalog.",
            ui_payload={
                "field": "property_type_catalog", "label": "Property catalog",
                "prompt": "Review the Property catalog.", "input_type": "property_type_catalog",
                "options": [], "examples": [], "allow_custom": False,
            },
        )
        db.add_all([administrator, project, profile, session, property_type, question]); db.commit()
        db.refresh(administrator); db.refresh(project)

        confirm_property_type_catalog(project.id, db, administrator)

        messages = db.query(ProjectMessage).filter_by(session_id=session.id).order_by(ProjectMessage.created_at).all()
        assert question.response_payload["answer"] == "Confirmed the current property type catalog"
        assert len(messages) == 2
        assert "I saved the Property catalog with 1 confirmed property type: Typology 1." in messages[-1].content
        assert "Let's continue:" in messages[-1].content
        assert messages[-1].ui_payload["input_type"] != "property_type_catalog"
    finally:
        db.close(); engine.dispose()


def test_plan_has_independent_property_type_and_unit_limits():
    plan = PlanCreate(name="Growth", max_property_types_per_project=12, max_properties_per_project=500)
    assert plan.max_property_types_per_project == 12
    assert plan.max_properties_per_project == 500


def test_property_type_rejects_inverted_area_range_and_normalizes_currency():
    valid = PropertyTypeCreate(
        name="Residence", area_min=90, area_max=110, available_units=2,
        starting_price=100000, currency="usd", inventory_updated_at=datetime.utcnow(),
    )
    assert valid.currency == "USD"

    import pytest
    with pytest.raises(ValueError, match="Area minimum"):
        PropertyTypeCreate(name="Residence", area_min=120, area_max=90)


def test_catalog_migration_avoids_json_boolean_bind_tokens():
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "20260814_company_catalog_media.py"
    content = migration.read_text(encoding="utf-8")
    assert ":true" not in content.casefold()
    assert "jsonb_build_object" in content
