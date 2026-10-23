import asyncio
from io import BytesIO
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pypdf import PdfWriter

import app.db.base  # noqa: F401
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects import asset_share_service, sales_asset_service, source_service, services as project_services
from app.modules.projects.models import (
    Project, ProjectOnboardingSource, ProjectProfile, ProjectSalesAsset,
    ProjectSourceKind, ProjectSourceStatus,
)
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.live_service import _denies_available_asset, _execute_share_actions, _select_asset_for_request
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_agent.response_policy import concise_channel_text, plain_channel_text, repeats_introduction_after_greeting


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
        "capabilities": [],
        "links": [],
    }]
    assert "share_url" not in context["available_assets"][0]


def test_upload_intent_materializes_a_draft_but_never_approves_it():
    db = _db()
    _, project, source = _project_source(db)
    source.sharing_intent = "sales_candidate"
    source.intended_asset_type = "brochure"
    source.intended_content_tags = ["brochure", "floor_plan"]
    source.intended_display_name = "Riverside buyer brochure"
    source.intended_allowed_channels = ["whatsapp"]
    db.add(source); db.commit(); db.refresh(source)

    item = sales_asset_service.materialize_source_candidate(db, source)
    db.commit()

    assert item is not None
    assert item.project_id == project.id
    assert item.display_name == "Riverside buyer brochure"
    assert item.allowed_channels == ["whatsapp"]
    assert item.content_tags == ["brochure", "floor_plan"]
    assert item.approval_status == "draft"
    assert item.approved_at is None
    assert sales_asset_service.materialize_source_candidate(db, source).id == item.id


def test_source_extraction_does_not_reopen_a_manually_corrected_name(monkeypatch):
    db = _db()
    _, project, source = _project_source(db)
    project.profile.profile_data = {"project_name": "Riverside Project"}
    project.profile.field_states = {"project_name": {"status": "corrected_by_user", "applicable": True}}
    project.profile.field_sources = {"project_name": {"source_type": "user"}}
    db.add(project.profile); db.commit(); db.refresh(source)
    monkeypatch.setattr(
        source_service,
        "get_ai_config",
        lambda *_args: type("Config", (), {"openrouter_api_key": "test", "agent_onboarding_proyectos": {}})(),
    )
    async def response(*_args, **_kwargs):
        return '{"proposals":[{"field":"project_name","value":"Riverside","evidence":"Cover"},{"field":"short_description","value":"A complete residential development with homes and shared amenities.","evidence":"Overview"}]}'

    monkeypatch.setattr(source_service, "generate_llm_response", response)
    proposals = asyncio.run(source_service._extract_proposals(db, source, "Riverside brochure content", None))

    assert [item.field_key for item in proposals] == ["short_description"]
    assert project.profile.profile_data["project_name"] == "Riverside Project"


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


def test_approved_brochure_with_floor_plans_is_selected_for_a_plan_request():
    db = _db()
    company, project, source = _project_source(db)
    source.extracted_text = "Depto. 508 Nivel 5 56.62 m². Recorrido 360."
    asset = ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="brochure", display_name="Project brochure", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
    )
    db.add(asset); db.commit()
    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )

    available = context["available_assets"]
    assert available[0]["capabilities"] == ["floor_plans", "virtual_tour"]
    assert _select_asset_for_request(available, "Can you send me the floor plans?")["asset_id"] == asset.id
    assert _denies_available_asset("I cannot send brochures directly.") is True


def test_draft_sales_material_blocks_final_confirmation():
    db = _db()
    company, project, source = _project_source(db)
    db.add(ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="brochure", content_tags=["brochure"], display_name="Buyer brochure",
        approval_status="draft", allowed_channels=["whatsapp"],
    ))
    db.commit()

    ready, reasons = project_services.readiness_for_confirmation(db, project)

    assert ready is False
    assert "pending_sales_materials" in reasons


def test_generic_material_question_is_offered_before_a_secure_link_is_issued(monkeypatch):
    db = _db()
    company, project, source = _project_source(db)
    asset = ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="brochure", content_tags=["brochure", "floor_plan"],
        display_name="Project brochure and plans", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
    )
    db.add(asset); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id="lead-1",
        provider="telnyx", channel="whatsapp", is_paused=False,
    )
    db.add(conversation); db.commit()
    commercial = {"available_assets": [{
        "asset_id": asset.id, "name": asset.display_name, "asset_type": "brochure",
        "capabilities": ["floor_plans"],
    }]}

    reply, actions, shares = _execute_share_actions(
        db, conversation=conversation, lead=type("Lead", (), {"id": "lead-1"})(),
        run=type("Run", (), {"id": "run-1"})(), reply="I can help.", actions=[],
        commercial=commercial, inbound_text="Do you have floor plans?",
    )
    assert "Would you like me to send the secure link here?" in reply
    assert actions == []
    assert shares == []
    assert conversation.pending_asset_id == asset.id

    monkeypatch.setattr(
        asset_share_service, "issue",
        lambda *_args, **_kwargs: ("https://blackpenguin.ai/a/token", type("Share", (), {"id": "share-1"})()),
    )
    reply, actions, shares = _execute_share_actions(
        db, conversation=conversation, lead=type("Lead", (), {"id": "lead-1"})(),
        run=type("Run", (), {"id": "run-1"})(), reply="Yes.", actions=[],
        commercial=commercial, inbound_text="Yes, please",
    )
    assert "https://blackpenguin.ai/a/token" in reply
    assert shares == ["share-1"]
    assert conversation.pending_asset_id is None


def test_explicit_material_request_issues_secure_link_without_redundant_confirmation(monkeypatch):
    db = _db()
    company, project, source = _project_source(db)
    asset = ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="brochure", content_tags=["brochure", "floor_plan"],
        display_name="Project brochure and plans", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
    )
    db.add(asset); db.flush()
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id="lead-1",
        provider="telnyx", channel="whatsapp", is_paused=False,
    )
    db.add(conversation); db.commit()
    monkeypatch.setattr(
        asset_share_service, "issue",
        lambda *_args, **_kwargs: ("https://blackpenguin.ai/a/token", type("Share", (), {"id": "share-1"})()),
    )
    reply, _, shares = _execute_share_actions(
        db, conversation=conversation, lead=type("Lead", (), {"id": "lead-1"})(),
        run=type("Run", (), {"id": "run-1"})(), reply="I can help.", actions=[],
        commercial={"available_assets": [{
            "asset_id": asset.id, "name": asset.display_name, "asset_type": "brochure",
            "capabilities": ["floor_plans"], "links": [],
        }]}, inbound_text="Can you send me the floor plans?",
    )
    assert "https://blackpenguin.ai/a/token" in reply
    assert shares == ["share-1"]
    assert conversation.pending_asset_id is None


def test_pdf_link_extraction_is_generic_and_classifies_virtual_tours():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_uri(0, "https://my.matterport.com/show/?m=example", (10, 10, 200, 40))
    writer.add_uri(0, "https://example.com/project", (10, 50, 200, 80))
    writer.write(output)

    links = source_service._extract_pdf_links(output.getvalue())
    assert [item["kind"] for item in links] == ["virtual_tour", "external_reference"]
    assert all(item["page"] == 1 for item in links)


def test_channel_text_converts_markdown_links_to_clickable_plain_urls():
    assert plain_channel_text("See [Project website](https://example.com/project).") == (
        "See Project website: https://example.com/project."
    )


def test_channel_text_keeps_mobile_replies_concise_at_sentence_boundaries():
    reply = " ".join(["Confirmed project information is available."] * 40)
    concise = concise_channel_text(reply, "sms")
    assert concise is not None
    assert len(concise) <= 700
    assert concise.endswith("I can share more detail on any of these points.")
