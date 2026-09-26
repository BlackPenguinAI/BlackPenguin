"""Provider-neutral live lead intake that launches a real SMS conversation."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import Lead, LeadConsentEvent
from app.integrations.messaging_gateway import live_provider, provider_sender

from .live_service import launch_live_lead, normalize_phone
from .models import SalesConversation
from .simulation_service import COMPLETED_PROJECT_STATUSES, _number, _selected_product


LIVE_LEAD_SOURCES = {
    "manual": {
        "label": "Manual registration",
        "requires_campaign": False,
        "campaign_platform": None,
        "lead_platform": "manual",
        "lead_source": "Manual registration",
    },
    "meta": {
        "label": "Meta Lead Ads",
        "requires_campaign": True,
        "campaign_platform": "meta",
        "lead_platform": "meta_test",
        "lead_source": "Meta Lead Ads · manual control test",
    },
}


def live_lead_source_options() -> list[dict]:
    return [
        {
            "code": code,
            "label": definition["label"],
            "requires_campaign": definition["requires_campaign"],
            "campaign_platform": definition["campaign_platform"],
        }
        for code, definition in LIVE_LEAD_SOURCES.items()
    ]


async def create_live_lead(
    db: Session,
    *,
    company_id: str,
    project_id: str,
    source_code: str,
    campaign_id: str | None,
    lead_form: dict,
    idempotency_key: str,
) -> dict:
    source_definition = LIVE_LEAD_SOURCES.get(source_code)
    if not source_definition:
        raise HTTPException(status_code=422, detail="Select a supported lead source.")
    provider = live_provider(db, company_id=company_id)
    if not provider:
        raise HTTPException(status_code=409, detail="Verify and enable the default SMS provider before submitting a live test lead.")
    thread_key = f"{provider}:{normalize_phone(provider_sender(db, provider, company_id=company_id))}:{normalize_phone(lead_form['phone'])}"
    foreign_thread = db.query(SalesConversation).filter(
        SalesConversation.provider_thread_key == thread_key,
        SalesConversation.company_id != company_id,
    ).first()
    if foreign_thread:
        raise HTTPException(
            status_code=409,
            detail="This phone already has a conversation for another Company on the shared SMS sender.",
        )
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.company_id == company_id,
        Project.is_active.is_(True),
        Project.is_demo.is_(False),
    ).first()
    approved = bool(project and project.profile and project.profile.final_approved)
    if not project or project.onboarding_status not in COMPLETED_PROJECT_STATUSES or not approved:
        raise HTTPException(status_code=409, detail="Select a completed, approved, non-Demo Project.")
    if source_definition["requires_campaign"] and not campaign_id:
        raise HTTPException(status_code=422, detail=f"A campaign is required for {source_definition['label']} leads.")
    campaign = None
    if campaign_id:
        campaign = db.query(ProjectCampaign).filter(
            ProjectCampaign.id == campaign_id,
            ProjectCampaign.project_id == project.id,
        ).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found for this Project.")
        expected_platform = source_definition["campaign_platform"]
        if expected_platform and campaign.platform != expected_platform:
            raise HTTPException(status_code=422, detail=f"Select a {source_definition['label']} campaign.")
    if source_code == "meta" and campaign and not campaign.lead_form_id:
        raise HTTPException(status_code=409, detail="Map this campaign to a Meta Lead Form before submitting a Meta lead.")
    if not lead_form.get("consent"):
        raise HTTPException(status_code=422, detail="Explicit SMS consent is required.")

    stable_id = hashlib.sha256(f"{company_id}:{source_code}:{idempotency_key}".encode()).hexdigest()[:48]
    external_id = f"manual:{stable_id}"
    existing = db.query(Lead).filter(
        Lead.platform == source_definition["lead_platform"],
        Lead.external_lead_id == external_id,
        Lead.company_id == company_id,
    ).first()
    if existing:
        conversation = db.query(SalesConversation).filter(
            SalesConversation.company_id == company_id,
            SalesConversation.provider_thread_key == thread_key,
        ).first()
        if not conversation or existing.agent_status in {
            "delivery_failed", "queued", "routing_blocked", "waiting_for_twilio",
        }:
            conversation, message = await launch_live_lead(db, existing)
        else:
            message = None
        return {
            "lead_id": existing.id,
            "conversation_id": conversation.id if conversation else "",
            "message_id": message.id if message else None,
            "status": existing.agent_status,
            "replayed": True,
            "provider": provider,
            "source_code": source_code,
        }

    product = _selected_product(db, project=project, product_id=lead_form["product_id"])
    now = datetime.utcnow()
    budget = {
        "minimum": _number(lead_form["budget_min"]),
        "maximum": _number(lead_form.get("budget_max")),
        "currency": product.get("currency"),
    }
    qualification = {
        "selected_product": product,
        "budget": budget,
        "custom_answers": lead_form.get("custom_answers") or {},
    }
    lead = Lead(
        company_id=company_id,
        project_id=project.id,
        campaign_id=campaign.id if campaign else None,
        full_name=f"{lead_form['first_name']} {lead_form['last_name']}".strip(),
        phone=lead_form["phone"],
        email=str(lead_form.get("email") or "") or None,
        source=source_definition["lead_source"],
        platform=source_definition["lead_platform"],
        external_lead_id=external_id,
        preferred_channel="sms",
        channel_address=lead_form["phone"],
        consent_status="granted_manual_meta_test",
        consent_captured_at=now,
        qualification_summary=json.dumps(qualification, ensure_ascii=False, default=str),
        meta_form_data=jsonable_encoder({
            "test_mode": "manual_meta_lead_ads",
            "form_id": campaign.lead_form_id,
            "campaign_id": campaign.external_campaign_id,
            "adset_id": campaign.external_adset_id,
            "ad_id": campaign.external_ad_id,
            "selected_product": product,
            "budget": budget,
            "custom_answers": lead_form.get("custom_answers") or {},
        }) if source_code == "meta" and campaign else {},
        agent_status="queued",
        is_demo=False,
        is_test=True,
    )
    db.add(lead); db.flush()
    db.add(LeadConsentEvent(
        lead_id=lead.id,
        channel="sms",
        action="consent_captured",
        source=f"live_lead_intake:{source_code}",
        evidence=f"Submitted by an authorized Company user as {source_definition['label']} with explicit SMS consent.",
    ))
    db.commit(); db.refresh(lead)
    try:
        conversation, message = await launch_live_lead(db, lead)
    except HTTPException as exc:
        lead.agent_status = "routing_blocked" if exc.status_code == 409 else "delivery_failed"
        db.commit()
        raise
    except Exception:
        lead.agent_status = "delivery_failed"
        db.commit()
        raise
    if not conversation:
        raise HTTPException(status_code=409, detail="The live SMS provider became unavailable before dispatch.")
    return {
        "lead_id": lead.id,
        "conversation_id": conversation.id,
        "message_id": message.id if message else None,
        "status": lead.agent_status,
        "replayed": False,
        "provider": provider,
        "source_code": source_code,
    }


async def create_live_meta_test(
    db: Session,
    *,
    company_id: str,
    project_id: str,
    campaign_id: str,
    lead_form: dict,
    idempotency_key: str,
) -> dict:
    """Backward-compatible Meta-specific entrypoint."""
    return await create_live_lead(
        db,
        company_id=company_id,
        project_id=project_id,
        source_code="meta",
        campaign_id=campaign_id,
        lead_form=lead_form,
        idempotency_key=idempotency_key,
    )
