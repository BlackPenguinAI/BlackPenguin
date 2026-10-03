"""Provider-neutral live lead intake that launches a real SMS conversation."""

from __future__ import annotations

from datetime import datetime
import hashlib

import httpx
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.modules.projects.meta_service import decrypt_connection_token
from app.modules.projects.models import MetaConnection, Project, ProjectCampaign
from app.modules.sales_crm.models import Lead, LeadConsentEvent
from app.modules.sales_crm.intelligence import initial_lead_profile, lead_profile_summary
from app.modules.system_settings.services import get_meta_platform_config
from app.integrations.messaging_gateway import channel_sender, company_live_channel, live_provider

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


_META_CONTACT_QUESTION_KEYS = {
    "email", "first_name", "full_name", "last_name", "name",
    "phone", "phone_number",
}


def _meta_question_options(question: dict) -> list[str]:
    values: list[str] = []
    for option in question.get("options") or []:
        if isinstance(option, dict):
            value = option.get("value") or option.get("label") or option.get("key")
        else:
            value = option
        if value not in (None, ""):
            values.append(str(value))
    return values


def _meta_form_questions(payload: dict) -> list[dict]:
    """Normalize Meta's question contract without exposing provider-only data."""
    questions: list[dict] = []
    for index, question in enumerate(payload.get("questions") or []):
        if not isinstance(question, dict):
            continue
        key = str(question.get("key") or question.get("name") or f"question_{index + 1}").strip()
        if not key or key.casefold() in _META_CONTACT_QUESTION_KEYS:
            continue
        label = str(question.get("label") or question.get("name") or key.replace("_", " ").title()).strip()
        questions.append({
            "key": key[:160],
            "label": label[:240],
            "type": str(question.get("type") or "CUSTOM").upper()[:40],
            "required": bool(question.get("required", False)),
            "options": _meta_question_options(question)[:100],
        })
    return questions


async def meta_lead_form_preview(
    db: Session, *, company_id: str, project_id: str, campaign_id: str,
) -> dict:
    """Load the mapped Lead Form definition for an authorized tenant Project."""
    campaign = db.query(ProjectCampaign).join(Project).filter(
        ProjectCampaign.id == campaign_id,
        ProjectCampaign.project_id == project_id,
        ProjectCampaign.platform == "meta",
        Project.company_id == company_id,
        Project.is_active.is_(True),
        Project.is_demo.is_(False),
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Meta campaign not found for this Project.")
    if not campaign.lead_form_id:
        raise HTTPException(status_code=409, detail="Map this campaign to a Meta Lead Form before loading its fields.")
    connection = db.query(MetaConnection).filter(
        MetaConnection.id == campaign.meta_connection_id,
        MetaConnection.company_id == company_id,
        MetaConnection.verification_mode == "real",
        MetaConnection.verification_status == "succeeded",
    ).first()
    if not connection:
        raise HTTPException(status_code=409, detail="Reconnect the verified Meta Page used by this campaign.")
    try:
        access_token = decrypt_connection_token(connection)
    except (HTTPException, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Reconnect Meta before loading this Lead Form.") from exc
    graph_version = get_meta_platform_config(db).graph_api_version
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"https://graph.facebook.com/{graph_version}/{campaign.lead_form_id}",
                params={
                    "access_token": access_token,
                    "fields": "id,name,status,questions",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Meta could not load the mapped Lead Form. Reconnect Meta and confirm Leads Access.",
        ) from exc
    if str(payload.get("id") or "") != str(campaign.lead_form_id):
        raise HTTPException(status_code=502, detail="Meta returned a different Lead Form than the mapped campaign.")
    return {
        "form_id": str(campaign.lead_form_id),
        "name": str(payload.get("name") or f"Meta Lead Form {campaign.lead_form_id}"),
        "status": str(payload.get("status") or "UNKNOWN"),
        "campaign_id": campaign.id,
        "external_campaign_id": campaign.external_campaign_id,
        "external_adset_id": campaign.external_adset_id,
        "external_ad_id": campaign.external_ad_id,
        "questions": _meta_form_questions(payload),
    }


async def create_live_lead(
    db: Session,
    *,
    company_id: str,
    project_id: str,
    source_code: str,
    campaign_id: str | None,
    channel: str | None = None,
    lead_form: dict,
    idempotency_key: str,
) -> dict:
    source_definition = LIVE_LEAD_SOURCES.get(source_code)
    if not source_definition:
        raise HTTPException(status_code=422, detail="Select a supported lead source.")
    channel = company_live_channel(db, company_id=company_id, requested=channel)
    if not channel:
        raise HTTPException(status_code=409, detail="Verify and enable an SMS or WhatsApp channel for this Company before starting the agent.")
    provider = "telnyx" if channel == "whatsapp" else live_provider(db, company_id=company_id)
    if not provider:
        raise HTTPException(status_code=409, detail="The selected Company messaging channel is not ready.")
    sender = normalize_phone(channel_sender(db, provider=provider, company_id=company_id, channel=channel))
    thread_key = (
        f"{provider}:{sender}:{normalize_phone(lead_form['phone'])}"
        if channel == "sms" else
        f"{provider}:{channel}:{sender}:{normalize_phone(lead_form['phone'])}"
    )
    foreign_thread = db.query(SalesConversation).filter(
        SalesConversation.provider_thread_key == thread_key,
        SalesConversation.company_id != company_id,
    ).first()
    if foreign_thread:
        raise HTTPException(
            status_code=409,
            detail="This phone already has a conversation for another Company on the shared sender.",
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
        raise HTTPException(status_code=422, detail=f"Explicit {channel.upper()} consent is required.")

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
            existing.preferred_channel = channel
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
            "channel": channel,
            "source_code": source_code,
        }

    product = (
        _selected_product(db, project=project, product_id=lead_form["product_id"])
        if lead_form.get("product_id") else None
    )
    now = datetime.utcnow()
    budget = None
    if lead_form.get("budget_min") is not None or lead_form.get("budget_max") is not None:
        budget = {
            "minimum": _number(lead_form.get("budget_min")),
            "maximum": _number(lead_form.get("budget_max")),
            "currency": product.get("currency") if product else None,
        }
    custom_answers = lead_form.get("custom_answers") or {}
    profile_source = "meta_form" if source_code == "meta" else "manual_registration"
    lead_profile = initial_lead_profile(
        product=product, budget=budget, custom_answers=custom_answers, source=profile_source,
    )
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
        preferred_channel=channel,
        channel_address=lead_form["phone"],
        consent_status="granted",
        consent_captured_at=now,
        qualification_summary=lead_profile_summary(lead_profile),
        meta_form_data=jsonable_encoder({
            "schema_version": 1,
            "test_mode": "manual_meta_lead_ads",
            "form_id": campaign.lead_form_id,
            "campaign_id": campaign.external_campaign_id,
            "adset_id": campaign.external_adset_id,
            "ad_id": campaign.external_ad_id,
            "answers": [
                {"key": str(key), "value": value}
                for key, value in custom_answers.items()
            ],
        }) if source_code == "meta" and campaign else {},
        lead_profile_data=jsonable_encoder(lead_profile),
        agent_status="queued",
        is_demo=False,
        is_test=source_code == "meta",
    )
    db.add(lead); db.flush()
    db.add(LeadConsentEvent(
        lead_id=lead.id,
        channel=channel,
        action="consent_captured",
        source=f"live_lead_intake:{source_code}",
        evidence=f"Submitted by an authorized Company user as {source_definition['label']} with explicit {channel.upper()} consent.",
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
        raise HTTPException(status_code=409, detail="The live messaging provider became unavailable before dispatch.")
    return {
        "lead_id": lead.id,
        "conversation_id": conversation.id,
        "message_id": message.id if message else None,
        "status": lead.agent_status,
        "replayed": False,
        "provider": provider,
        "channel": channel,
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
        channel="sms",
        lead_form=lead_form,
        idempotency_key=idempotency_key,
    )
