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

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.meta_leads.router import _resolve_campaign
from app.modules.projects.models import MetaConnection, Project, ProjectCampaign, ProjectProfile, ProjectPropertyType
from app.modules.sales_agent.live_test_service import create_live_meta_test
from app.modules.sales_agent.models import SalesConversation, SalesConversationLeadContext, SalesMessage
from app.modules.sales_crm.models import Lead, LeadContact
from app.modules.system_settings.models import TwilioConfig


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _project(db, company, *, name="Project", form_id="12345", ad_id="34567"):
    project = Project(company_id=company.id, name=name, onboarding_status="completed", is_active=True)
    db.add(project); db.flush()
    db.add(ProjectProfile(project_id=project.id, final_approved=True, profile_data={}, field_states={}))
    campaign = ProjectCampaign(
        project_id=project.id, name=f"{name} campaign", platform="meta", status="draft",
        external_campaign_id="23456", external_adset_id="23457", external_ad_id=ad_id,
        lead_form_id=form_id,
    )
    product = ProjectPropertyType(
        project_id=project.id, name="Two bedrooms", review_status="confirmed",
        starting_price=500000, currency="USD",
    )
    db.add_all([campaign, product]); db.commit()
    return project, campaign, product


def _lead_form(product, phone="+13055550142"):
    return {
        "first_name": "Taylor", "last_name": "Morgan", "phone": phone,
        "email": "taylor@example.com", "product_id": f"property_type:{product.id}",
        "budget_min": 550000, "budget_max": 650000, "consent": True,
        "custom_answers": {"timeline": "this year"},
    }


def test_manual_meta_control_is_one_idempotent_real_sms_action():
    db = _db(); company = Company(name="Tenant A"); db.add(company); db.flush()
    project, campaign, product = _project(db, company)
    db.add(TwilioConfig(
        account_sid="AC" + ("1" * 32), from_phone_number="+18573824206",
        live_sms_enabled=True, verification_status="verified",
    )); db.commit()
    with patch("app.modules.sales_agent.live_service.send_sms", new=AsyncMock(return_value={"sid": "SM1", "status": "queued"})) as sms:
        first = asyncio.run(create_live_meta_test(
            db, company_id=company.id, project_id=project.id, campaign_id=campaign.id,
            lead_form=_lead_form(product), idempotency_key="manual-request-0001",
        ))
        replay = asyncio.run(create_live_meta_test(
            db, company_id=company.id, project_id=project.id, campaign_id=campaign.id,
            lead_form=_lead_form(product), idempotency_key="manual-request-0001",
        ))
    assert first["replayed"] is False and replay["replayed"] is True
    assert replay["conversation_id"] == first["conversation_id"]
    assert db.query(Lead).filter_by(platform="meta_test").count() == 1
    assert db.query(SalesMessage).count() == 1
    assert sms.await_count == 1


def test_same_company_phone_keeps_one_thread_and_changes_project_context():
    db = _db(); company = Company(name="Tenant A"); db.add(company); db.flush()
    first_project, first_campaign, first_product = _project(db, company, name="North")
    second_project, second_campaign, second_product = _project(db, company, name="South", form_id="12346", ad_id="34568")
    db.add(TwilioConfig(
        account_sid="AC" + ("1" * 32), from_phone_number="+18573824206",
        live_sms_enabled=True, verification_status="verified",
    )); db.commit()
    with patch("app.modules.sales_agent.live_service.send_sms", new=AsyncMock(side_effect=[
        {"sid": "SM1", "status": "queued"}, {"sid": "SM2", "status": "queued"},
    ])):
        first = asyncio.run(create_live_meta_test(
            db, company_id=company.id, project_id=first_project.id, campaign_id=first_campaign.id,
            lead_form=_lead_form(first_product), idempotency_key="manual-request-0001",
        ))
        second = asyncio.run(create_live_meta_test(
            db, company_id=company.id, project_id=second_project.id, campaign_id=second_campaign.id,
            lead_form=_lead_form(second_product), idempotency_key="manual-request-0002",
        ))
    assert first["conversation_id"] == second["conversation_id"]
    conversation = db.query(SalesConversation).one()
    assert conversation.project_id == second_project.id
    assert db.query(Lead).count() == 2
    assert db.query(LeadContact).count() == 1
    assert db.query(SalesMessage).count() == 2
    contexts = db.query(SalesConversationLeadContext).all()
    assert len(contexts) == 2
    assert sum(item.is_active for item in contexts) == 1


def test_failed_twilio_dispatch_can_retry_without_duplicate_lead_or_message():
    db = _db(); company = Company(name="Tenant A"); db.add(company); db.flush()
    project, campaign, product = _project(db, company)
    db.add(TwilioConfig(
        account_sid="AC" + ("1" * 32), from_phone_number="+18573824206",
        live_sms_enabled=True, verification_status="verified",
    )); db.commit()
    with patch("app.modules.sales_agent.live_service.send_sms", new=AsyncMock(side_effect=RuntimeError("Twilio timeout"))):
        with pytest.raises(RuntimeError, match="Twilio timeout"):
            asyncio.run(create_live_meta_test(
                db, company_id=company.id, project_id=project.id, campaign_id=campaign.id,
                lead_form=_lead_form(product), idempotency_key="manual-request-retry",
            ))
    with patch("app.modules.sales_agent.live_service.send_sms", new=AsyncMock(return_value={"sid": "SM-retry", "status": "queued"})):
        replay = asyncio.run(create_live_meta_test(
            db, company_id=company.id, project_id=project.id, campaign_id=campaign.id,
            lead_form=_lead_form(product), idempotency_key="manual-request-retry",
        ))
    assert replay["replayed"] is True and replay["message_id"]
    assert db.query(Lead).count() == 1
    assert db.query(SalesMessage).count() == 1
    assert db.query(SalesMessage).one().status == "queued"


def test_shared_sender_blocks_cross_company_phone_collision_before_creating_lead():
    db = _db(); first_company = Company(name="A"); second_company = Company(name="B")
    db.add_all([first_company, second_company]); db.flush()
    first_project, first_campaign, first_product = _project(db, first_company, name="First")
    second_project, second_campaign, second_product = _project(db, second_company, name="Second", form_id="12346")
    db.add(TwilioConfig(
        account_sid="AC" + ("1" * 32), from_phone_number="+18573824206",
        live_sms_enabled=True, verification_status="verified",
    )); db.commit()
    with patch("app.modules.sales_agent.live_service.send_sms", new=AsyncMock(return_value={"sid": "SM1", "status": "queued"})):
        asyncio.run(create_live_meta_test(
            db, company_id=first_company.id, project_id=first_project.id, campaign_id=first_campaign.id,
            lead_form=_lead_form(first_product), idempotency_key="manual-request-0001",
        ))
        with pytest.raises(HTTPException, match="another Company") as collision:
            asyncio.run(create_live_meta_test(
                db, company_id=second_company.id, project_id=second_project.id, campaign_id=second_campaign.id,
                lead_form=_lead_form(second_product), idempotency_key="manual-request-0002",
            ))
    assert collision.value.status_code == 409
    assert db.query(Lead).filter_by(company_id=second_company.id).count() == 0


def test_meta_route_prefers_exact_ad_and_rejects_ambiguous_form_reuse():
    db = _db(); company = Company(name="Tenant"); db.add(company); db.flush()
    connection = MetaConnection(
        company_id=company.id, label="Corporate Meta", page_id="99999", ad_account_id="88888",
        verification_mode="real", verification_status="succeeded",
    )
    db.add(connection); db.flush()
    first_project, first_campaign, _ = _project(db, company, name="First", ad_id="11111")
    second_project, second_campaign, _ = _project(db, company, name="Second", ad_id="22222")
    first_campaign.meta_connection_id = connection.id
    second_campaign.meta_connection_id = connection.id
    db.commit()
    exact, error = _resolve_campaign(db, page_id="99999", form_id="12345", ad_id="22222")
    assert error is None and exact.id == second_campaign.id
    missing, error = _resolve_campaign(db, page_id="99999", form_id="12345", ad_id=None)
    assert missing is None and "Ambiguous" in error


def test_meta_live_sms_migration_is_repeatable(monkeypatch):
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260905_meta_live_sms_testing.py"
    spec = importlib.util.spec_from_file_location("meta_live_sms_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        lead_columns = {item["name"] for item in connection.dialect.get_columns(connection, "leads")}
        campaign_columns = {item["name"] for item in connection.dialect.get_columns(connection, "project_campaigns")}
    assert "is_test" in lead_columns
    assert {"external_adset_id", "external_ad_id"}.issubset(campaign_columns)
