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
from app.modules.sales_agent.live_service import (
    _denies_available_asset, _execute_share_actions, _normalize_asset_request_result,
    _reconcile_shared_asset_reply, _select_asset_for_request, _select_assets_for_request,
)
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
        "content_tags": ["brochure"],
        "name": "Riverside brochure", "description": "Approved project overview",
        "mime_type": "application/pdf", "has_file": True, "version": 1,
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


def test_source_extraction_never_turns_public_contacts_into_internal_assignments(monkeypatch):
    db = _db()
    _, _, source = _project_source(db)
    monkeypatch.setattr(
        source_service,
        "get_ai_config",
        lambda *_args: type("Config", (), {"openrouter_api_key": "test", "agent_onboarding_proyectos": {}})(),
    )

    async def response(*_args, **_kwargs):
        return '{"proposals":[{"field":"sales_contacts","value":[{"name":"Public sales office","phone":"+1 555 0100"}],"evidence":"Footer"},{"field":"appointment_routing","value":"manual","evidence":"Footer"},{"field":"short_description","value":"A residential development with practical layouts.","evidence":"Overview"}]}'

    monkeypatch.setattr(source_service, "generate_llm_response", response)
    proposals = asyncio.run(source_service._extract_proposals(db, source, "Public sales office +1 555 0100", None))

    assert [item.field_key for item in proposals] == ["short_description"]


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
        asset_type="brochure", content_tags=["brochure", "floor_plan"],
        display_name="Project brochure", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
    )
    db.add(asset); db.commit()
    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )

    available = context["available_assets"]
    assert available[0]["capabilities"] == ["floor_plans"]
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
    issued_targets = []

    def issue(*_args, **kwargs):
        issued_targets.append(kwargs.get("target_url"))
        return "https://blackpenguin.ai/a/token", type("Share", (), {"id": "share-1"})()

    monkeypatch.setattr(asset_share_service, "issue", issue)
    reply, _, shares = _execute_share_actions(
        db, conversation=conversation, lead=type("Lead", (), {"id": "lead-1"})(),
        run=type("Run", (), {"id": "run-1"})(), reply="I can help.", actions=[],
        commercial={"available_assets": [{
            "asset_id": asset.id, "name": asset.display_name, "asset_type": "brochure",
            "capabilities": ["floor_plans"], "links": [
                {"url": "https://maps.example/project", "label": "Location map", "kind": "location_map"},
                {"url": "https://tour.example/project", "label": "360 tour", "kind": "virtual_tour"},
            ],
        }]}, inbound_text="Can you send me the floor plans?",
    )
    assert "https://blackpenguin.ai/a/token" in reply
    assert shares == ["share-1"]
    assert issued_targets == [None]
    assert "Location map" not in reply and "360 tour" not in reply
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


def test_website_link_extraction_keeps_useful_project_resources_only():
    html = b"""
    <html><body>
      <a href="/downloads/brochure.pdf">Download brochure</a>
      <iframe src="https://my.matterport.com/show/?m=abc" title="360 tour"></iframe>
      <a href="https://example.com/privacy">Privacy</a>
      <a href="http://127.0.0.1/private.pdf">Project PDF</a>
    </body></html>
    """
    links = source_service._extract_html_links(html, "https://example.com/project")

    assert [item["kind"] for item in links] == ["external_reference", "virtual_tour"]
    assert links[0]["url"] == "https://example.com/downloads/brochure.pdf"
    assert all("privacy" not in item["url"] and "127.0.0.1" not in item["url"] for item in links)


def test_discovered_website_links_create_a_reviewable_draft():
    db = _db()
    _, _, source = _project_source(db)
    source.kind = ProjectSourceKind.URL
    source.storage_path = None
    source.url = "https://example.com/project"
    source.name = "example.com"
    source.extracted_links = [{
        "url": "https://my.matterport.com/show/?m=abc", "label": "360 tour",
        "kind": "virtual_tour", "page": None,
    }]
    db.add(source); db.commit(); db.refresh(source)

    item = sales_asset_service.materialize_discovered_link_candidate(db, source)
    db.commit()

    assert item is not None
    assert item.asset_type == "virtual_tour"
    assert item.content_tags == ["virtual_tour"]
    assert item.approval_status == "draft"
    sales_asset_service.approve(db, item, user_id="admin-1")
    assert sales_asset_service.approved_for_turn(
        db, project_id=item.project_id, company_id=item.company_id, channel="whatsapp",
    )[0].id == item.id

    tracked_url, share = asset_share_service.issue(
        db, company_id=item.company_id, project_id=item.project_id, lead_id="lead-1",
        source_id=source.id, sales_asset_id=item.id, channel="whatsapp",
        target_url=source.extracted_links[0]["url"],
    )
    db.commit()
    token = tracked_url.rsplit("/", 1)[-1]
    resolved_source, resolved_share = asset_share_service.resolve(db, token)
    assert resolved_source.id == source.id
    assert resolved_share.target_url == "https://my.matterport.com/show/?m=abc"
    overview = project_services.serialize_overview(db, source.project)
    assert overview["materials"][0]["approval_status"] == "approved"
    assert overview["materials"][0]["content_tags"] == ["virtual_tour"]
    assert overview["materials"][0]["extracted_links"][0]["kind"] == "virtual_tour"


def test_partial_topic_matching_returns_every_useful_approved_resource():
    assets = [
        {"asset_id": "a-c", "asset_type": "brochure", "content_tags": ["brochure", "floor_plan"], "capabilities": []},
        {"asset_id": "c-only", "asset_type": "floor_plan", "content_tags": ["floor_plan"], "capabilities": []},
        {"asset_id": "unrelated", "asset_type": "legal_disclaimer", "content_tags": ["legal_disclaimer"], "capabilities": []},
    ]

    selected = _select_assets_for_request(
        assets, "Please send the brochure, price list and floor plans.",
    )

    assert [item["asset_id"] for item in selected] == ["a-c", "c-only"]


def test_invalid_model_asset_id_does_not_force_human_review_when_library_can_resolve_it():
    result, actions = _normalize_asset_request_result(
        {
            "policy_violations": ["share_asset_not_approved"],
            "requires_human": True,
        },
        [{"type": "share_asset", "asset_id": "invented"}],
        [{"asset_id": "approved"}],
    )

    assert result["policy_violations"] == []
    assert result["requires_human"] is False
    assert actions == []


def test_explicit_multi_topic_request_shares_all_partially_matching_assets(monkeypatch):
    db = _db()
    company, project, source = _project_source(db)
    assets = []
    second_source = ProjectOnboardingSource(
        project_id=project.id, kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY, name="plans.pdf", original_filename="plans.pdf",
        mime_type="application/pdf", storage_path="projects/riverside/plans.enc", is_encrypted=True,
    )
    db.add(second_source); db.flush()
    for asset_id, tags, name, source_id in (
        ("asset-a-c", ["brochure", "floor_plan"], "Brochure and plans", source.id),
        ("asset-c", ["floor_plan"], "Additional plans", second_source.id),
    ):
        item = ProjectSalesAsset(
            id=asset_id, company_id=company.id, project_id=project.id, source_id=source_id,
            asset_type=tags[0], content_tags=tags, display_name=name,
            approval_status="approved", approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
        )
        db.add(item)
        assets.append(item)
    conversation = SalesConversation(
        company_id=company.id, project_id=project.id, lead_id="lead-1",
        provider="telnyx", channel="whatsapp", is_paused=False,
    )
    db.add(conversation); db.commit()
    issued = []

    def issue(*_args, **kwargs):
        issued.append(kwargs["sales_asset_id"])
        number = len(issued)
        return f"https://blackpenguin.ai/a/token-{number}", type("Share", (), {"id": f"share-{number}"})()

    monkeypatch.setattr(asset_share_service, "issue", issue)
    reply, _, shares = _execute_share_actions(
        db, conversation=conversation, lead=type("Lead", (), {"id": "lead-1"})(),
        run=type("Run", (), {"id": "run-1"})(), reply="Here are the resources.", actions=[],
        commercial={"available_assets": [
            {"asset_id": assets[0].id, "name": assets[0].display_name, "asset_type": "brochure", "content_tags": assets[0].content_tags, "capabilities": [], "links": [], "has_file": True},
            {"asset_id": assets[1].id, "name": assets[1].display_name, "asset_type": "floor_plan", "content_tags": assets[1].content_tags, "capabilities": [], "links": [], "has_file": True},
        ]},
        inbound_text="Please send the brochure, price list and floor plans.",
    )

    assert issued == ["asset-a-c", "asset-c"]
    assert shares == ["share-1", "share-2"]
    assert "token-1" in reply and "token-2" in reply
    assert "don't currently have an approved price list" in reply


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


def test_channel_compaction_preserves_property_list_boundaries():
    reply = "Here are the options:\n\n1. Studio\n   42 m².\n\n2. Two bedrooms\n   80–95 m².\n\n" + "Details. " * 120
    concise = concise_channel_text(reply, "sms")
    assert "1. Studio\n" in concise
    assert "\n\n2. Two bedrooms\n" in concise


def test_shared_asset_reconciliation_removes_denial_and_email_promise_only():
    reply = (
        "The confirmed starting price is 250,000 USD. "
        "I can't provide the floor plans directly. "
        "I can share the brochure via email if you provide your email address."
    )
    cleaned = _reconcile_shared_asset_reply(reply)
    assert cleaned == "The confirmed starting price is 250,000 USD."


def test_shared_asset_reconciliation_preserves_catalog_line_breaks():
    reply = (
        "Confirmed home types:\n\n"
        "1. Studio\n"
        "   42 m².\n\n"
        "2. Two bedrooms\n"
        "   80–95 m².\n\n"
        "I can't provide the floor plans directly."
    )

    cleaned = _reconcile_shared_asset_reply(reply)

    assert "1. Studio\n" in cleaned
    assert "\n\n2. Two bedrooms\n" in cleaned
    assert "can't provide" not in cleaned


def test_location_map_source_text_cannot_masquerade_as_floor_plan_capability():
    db = _db()
    company, project, source = _project_source(db)
    source.kind = ProjectSourceKind.URL
    source.storage_path = None
    source.extracted_text = "Apartments, units and 56.62 m² floor plan information."
    source.extracted_links = [{
        "url": "https://example.com/map", "label": "Location map",
        "kind": "location_map", "page": None,
    }]
    asset = ProjectSalesAsset(
        company_id=company.id, project_id=project.id, source_id=source.id,
        asset_type="location_map", content_tags=["location_map"],
        display_name="Project map", approval_status="approved",
        approved_at=datetime.utcnow(), allowed_channels=["whatsapp"],
    )
    db.add_all([source, asset]); db.commit()

    context = build_commercial_context(
        db, project=project, company_id=company.id, lead_id="lead-1", channel="whatsapp",
    )

    assert context["available_assets"][0]["capabilities"] == ["location_map"]
    assert _select_assets_for_request(
        context["available_assets"], "Please send the blueprints.",
    ) == []
