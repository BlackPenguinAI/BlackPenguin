from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.completion import FIELDS
from app.modules.projects.models import (
    Project,
    ProjectOnboardingSource,
    ProjectProfile,
    ProjectSalesAsset,
    ProjectSession,
    ProjectSourceKind,
    ProjectSourceStatus,
)
from app.modules.projects import services
from app.modules.projects.router import _guided_next_question
from app.modules.users.models import User, UserRole


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _resolved_states():
    states = {}
    for field in FIELDS:
        if field.requirement == "conditionally_required":
            states[field.key] = {"status": "not_applicable", "applicable": False}
        elif field.requirement == "required":
            states[field.key] = {"status": "confirmed", "applicable": True}
    return states


def _project_with_profile(db):
    company = Company(name="Tenant")
    db.add(company); db.flush()
    admin = User(
        company_id=company.id, email="admin@example.com", hashed_password="unused",
        role=UserRole.ADMIN, is_active=True,
    )
    project = Project(company_id=company.id, name="Demo", onboarding_status="in_progress")
    db.add_all([admin, project]); db.flush()
    profile = ProjectProfile(
        project_id=project.id,
        profile_data={"project_name": "Demo"},
        field_states=_resolved_states(),
    )
    db.add_all([profile, ProjectSession(project_id=project.id)]); db.commit()
    db.refresh(project); db.refresh(profile)
    return admin, project, profile


def test_profile_can_be_100_percent_while_final_approval_is_blocked_by_draft_material():
    db = _db()
    _admin, project, profile = _project_with_profile(db)
    source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.URL, status=ProjectSourceStatus.READY,
        name="fouquetsmiami.com", url="https://fouquetsmiami.com",
    )
    db.add(source); db.flush()
    asset = ProjectSalesAsset(
        company_id=project.company_id, project_id=project.id, source_id=source.id,
        asset_type="location_map", display_name="Resources from fouquetsmiami.com",
        approval_status="draft", allowed_channels=["sms", "whatsapp"],
    )
    db.add(asset); db.commit()

    payload = services.enrich_finalization_readiness(db, project, services.serialize_profile(profile))

    assert payload["completion"]["percentage"] == 100
    assert payload["completion"]["can_finalize"] is False
    assert payload["completion"]["ready_for_confirmation"] is False
    assert payload["completion"]["finalization_blockers"] == [{
        "code": "pending_sales_materials",
        "message": "Decide whether each draft file can be shared with leads or must remain internal.",
        "action": "review_sales_materials",
        "count": 1,
        "entity_ids": [asset.id],
        "labels": ["Resources from fouquetsmiami.com"],
    }]
    question = _guided_next_question(db, project, profile)
    assert question["input_type"] == "finalization_review"
    assert question["label"] == "Onboarding review required"
    assert "1 onboarding item" in question["prompt"]


def test_final_approval_conflict_keeps_actionable_blocker_details():
    db = _db()
    admin, project, _profile = _project_with_profile(db)
    source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.URL, status=ProjectSourceStatus.READY,
        name="source", url="https://example.com",
    )
    db.add(source); db.flush()
    db.add(ProjectSalesAsset(
        company_id=project.company_id, project_id=project.id, source_id=source.id,
        asset_type="brochure", display_name="Project brochure", approval_status="draft",
    )); db.commit()

    try:
        services.complete_onboarding(db, project, admin.id)
        raise AssertionError("Expected final approval to be blocked")
    except HTTPException as error:
        assert error.status_code == 409
        assert error.detail["blockers"] == ["pending_sales_materials"]
        assert error.detail["blocker_details"][0]["labels"] == ["Project brochure"]
        assert "Resolve the listed onboarding items" in error.detail["next_action"]


def test_resolving_draft_material_allows_final_approval_without_relaxing_gate():
    db = _db()
    admin, project, profile = _project_with_profile(db)
    source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.URL, status=ProjectSourceStatus.READY,
        name="source", url="https://example.com",
    )
    db.add(source); db.flush()
    asset = ProjectSalesAsset(
        company_id=project.company_id, project_id=project.id, source_id=source.id,
        asset_type="brochure", display_name="Project brochure", approval_status="draft",
    )
    db.add(asset); db.commit()

    asset.approval_status = "archived"
    db.add(asset); db.commit()
    payload = services.enrich_finalization_readiness(db, project, services.serialize_profile(profile))
    assert payload["completion"]["can_finalize"] is True
    assert _guided_next_question(db, project, profile)["label"] == "Final approval"

    completed = services.complete_onboarding(db, project, admin.id)
    assert completed.final_approved is True
    assert project.onboarding_status == "completed"
    completed_payload = services.enrich_finalization_readiness(db, project, services.serialize_profile(completed))
    assert completed_payload["completion"]["can_finalize"] is False
    assert completed_payload["completion"]["finalization_blockers"] == []
