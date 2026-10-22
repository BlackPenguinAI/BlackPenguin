from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects import asset_share_service, sales_asset_service
from app.modules.projects.models import (
    Project, ProjectOnboardingSource, ProjectProfile, ProjectSalesAsset,
    ProjectSourceKind, ProjectSourceStatus,
)
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.response_policy import repeats_introduction_after_greeting


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _project_source(db):
    company = Company(name="Sales Assets Company")
    db.add(company); db.flush()
    project = Project(company_id=company.id, name="Riverside")
    project.profile = ProjectProfile(profile_data={}, field_states={})
    db.add(project); db.flush()
    source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY, name="brochure.pdf",
        original_filename="brochure.pdf", mime_type="application/pdf",
        storage_path="projects/riverside/brochure.enc", is_encrypted=True,
    )
    db.add(source); db.commit()
    return company, project, source


def test_onboarding_file_is_private_until_separately_approved():
    db = _db()
    company, project, source = _project_source(db)

    private_context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )
    assert private_context["available_assets"] == []

    item = sales_asset_service.create(db, project, {
        "source_id": source.id, "property_type_id": None, "asset_type": "brochure",
        "display_name": "Riverside brochure", "description": "Approved project overview",
        "valid_from": None, "valid_until": datetime.utcnow() + timedelta(days=30),
        "allowed_channels": ["sms", "whatsapp"],
    }, user_id="admin-1")
    assert item.approval_status == "draft"
    assert build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )["available_assets"] == []

    sales_asset_service.approve(db, item, user_id="admin-1")
    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )
    assert context["available_assets"] == [{
        "asset_id": item.id, "asset_type": "brochure", "property_type": None,
        "name": "Riverside brochure", "description": "Approved project overview",
        "mime_type": "application/pdf", "version": 1,
        "valid_until": context["available_assets"][0]["valid_until"],
        "allowed_channels": ["sms", "whatsapp"],
    }]
    assert "share_url" not in context["available_assets"][0]


def test_asset_channel_and_expiration_are_enforced():
    db = _db()
    company, project, source = _project_source(db)
    db.add(ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="floor_plan", display_name="Floor plan", approval_status="approved",
        approved_at=datetime.utcnow(), valid_until=datetime.utcnow() - timedelta(seconds=1),
        allowed_channels=["whatsapp"],
    )); db.commit()
    assert sales_asset_service.approved_for_turn(
        db, project_id=project.id, company_id=company.id, channel="whatsapp",
    ) == []
    assert sales_asset_service.approved_for_turn(
        db, project_id=project.id, company_id=company.id, channel="sms",
    ) == []


def test_opaque_share_can_be_revoked_and_keeps_immutable_events():
    db = _db()
    company, project, source = _project_source(db)
    asset = ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="brochure", display_name="Brochure", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["sms"],
    )
    db.add(asset); db.flush()
    url, share = asset_share_service.issue(
        db, company_id=company.id, project_id=project.id, lead_id="lead-1",
        source_id=source.id, sales_asset_id=asset.id, channel="sms",
    )
    db.commit()
    token = url.rsplit("/", 1)[-1]
    assert "." not in token
    assert asset_share_service.resolve(db, token)[1].id == share.id
    asset_share_service.revoke(db, share, user_id="admin-1")
    with pytest.raises(HTTPException) as error:
        asset_share_service.resolve(db, token)
    assert error.value.status_code == 404
    assert [event.event_type for event in db.query(asset_share_service.SalesAssetAccessEvent).all()] == [
        "link_issued", "revoked",
    ]
    db.delete(share); db.commit()
    retained = db.query(asset_share_service.SalesAssetAccessEvent).all()
    assert len(retained) == 2
    assert all(event.company_id == company.id and event.asset_name == "Brochure" for event in retained)


def test_semantic_welcome_is_not_repeated_after_initial_template():
    history = [
        {"role": "assistant", "content": "Hi Jorge, thanks for your interest in Riverside. I'm Black Penguin's AI Sales Agent."},
        {"role": "user", "content": "Hello"},
    ]
    assert repeats_introduction_after_greeting(
        "Hello Jorge! How can I assist you today?", "Hello", history,
    ) is True
