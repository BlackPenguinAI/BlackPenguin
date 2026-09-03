"""Manual Meta Lead Ads test intake that launches a real Twilio conversation."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import Lead, LeadConsentEvent
from app.modules.system_settings.services import get_twilio_config

from .live_service import launch_live_lead, normalize_phone
from .models import SalesConversation
from .simulation_service import COMPLETED_PROJECT_STATUSES, _number, _selected_product


async def create_live_meta_test(
    db: Session,
    *,
    company_id: str,
    project_id: str,
    campaign_id: str,
    lead_form: dict,
    idempotency_key: str,
) -> dict:
    config = get_twilio_config(db)
    if not config.live_sms_enabled or config.verification_status != "verified":
        raise HTTPException(status_code=409, detail="Verify and enable Twilio live SMS before submitting a live test lead.")
    thread_key = f"twilio:{normalize_phone(config.from_phone_number or '')}:{normalize_phone(lead_form['phone'])}"
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
    campaign = db.query(ProjectCampaign).filter(
        ProjectCampaign.id == campaign_id,
        ProjectCampaign.project_id == project.id,
        ProjectCampaign.platform == "meta",
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Meta campaign not found for this Project.")
    if not campaign.lead_form_id:
        raise HTTPException(status_code=409, detail="Map this campaign to a Meta Lead Form before running a live test.")
    if not lead_form.get("consent"):
        raise HTTPException(status_code=422, detail="Explicit SMS consent is required.")

    stable_id = hashlib.sha256(f"{company_id}:{idempotency_key}".encode()).hexdigest()[:48]
    external_id = f"manual:{stable_id}"
    existing = db.query(Lead).filter(
        Lead.platform == "meta_test",
        Lead.external_lead_id == external_id,
        Lead.company_id == company_id,
    ).first()
    if existing:
        conversation = db.query(SalesConversation).filter(
            SalesConversation.company_id == company_id,
            SalesConversation.provider_thread_key == thread_key,
        ).first()
        if not conversation or existing.agent_status in {"delivery_failed", "queued", "waiting_for_twilio"}:
            conversation, message = await launch_live_lead(db, existing)
        else:
            message = None
        return {
            "lead_id": existing.id,
            "conversation_id": conversation.id if conversation else "",
            "message_id": message.id if message else None,
            "status": existing.agent_status,
            "replayed": True,
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
        campaign_id=campaign.id,
        full_name=f"{lead_form['first_name']} {lead_form['last_name']}".strip(),
        phone=lead_form["phone"],
        email=str(lead_form.get("email") or "") or None,
        source="Meta Lead Ads · manual control test",
        platform="meta_test",
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
        }),
        agent_status="queued",
        is_demo=False,
        is_test=True,
    )
    db.add(lead); db.flush()
    db.add(LeadConsentEvent(
        lead_id=lead.id,
        channel="sms",
        action="consent_captured",
        source="manual_meta_test_form",
        evidence="Submitted by an authorized Company user to test the configured Meta-to-SMS route.",
    ))
    db.commit(); db.refresh(lead)
    try:
        conversation, message = await launch_live_lead(db, lead)
    except HTTPException:
        lead.agent_status = "routing_blocked"
        db.commit()
        raise
    except Exception:
        lead.agent_status = "delivery_failed"
        db.commit()
        raise
    if not conversation:
        raise HTTPException(status_code=409, detail="Twilio live SMS became unavailable before dispatch.")
    return {
        "lead_id": lead.id,
        "conversation_id": conversation.id,
        "message_id": message.id if message else None,
        "status": lead.agent_status,
        "replayed": False,
    }
