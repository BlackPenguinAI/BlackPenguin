from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.postgres import get_db
from app.modules.projects.models import MetaConnection, Project, ProjectCampaign
from app.modules.projects.meta_service import decrypt_connection_token
from app.modules.sales_agent.models import ExternalWebhookEvent
from app.modules.sales_agent.live_service import start_live_lead
from app.modules.sales_crm.models import Lead, LeadConsentEvent


router = APIRouter()


def _valid_signature(body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(settings.META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


async def _fetch_lead(leadgen_id: str, access_token: str) -> dict:
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{leadgen_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url, params={
            "access_token": access_token,
            "fields": "id,created_time,ad_id,form_id,field_data",
        })
        response.raise_for_status()
        return response.json()


def _fields(payload: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in payload.get("field_data", []):
        values = field.get("values") or []
        if field.get("name") and values:
            result[str(field["name"]).casefold()] = str(values[0])
    return result


@router.get("/meta")
def verify(
    mode: str = Query(..., alias="hub.mode"),
    token: str = Query(..., alias="hub.verify_token"),
    challenge: str = Query(..., alias="hub.challenge"),
):
    if mode == "subscribe" and hmac.compare_digest(token, settings.META_VERIFY_TOKEN):
        return int(challenge)
    raise HTTPException(status_code=403, detail="Invalid verification token.")


@router.post("/meta")
async def receive(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    db: Session = Depends(get_db),
):
    body = await request.body()
    if not _valid_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid Meta signature.")
    payload = json.loads(body)
    accepted = 0
    duplicates = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value") or {}
            leadgen_id = value.get("leadgen_id")
            form_id = value.get("form_id")
            if not leadgen_id or not form_id:
                continue
            event_id = str(leadgen_id)
            if db.query(ExternalWebhookEvent).filter(
                ExternalWebhookEvent.platform == "meta",
                ExternalWebhookEvent.external_event_id == event_id,
            ).first():
                duplicates += 1
                continue
            event = ExternalWebhookEvent(
                platform="meta",
                external_event_id=event_id,
                event_type="leadgen",
                payload_json={"leadgen_id": leadgen_id, "form_id": form_id, "page_id": value.get("page_id")},
            )
            db.add(event)
            try:
                event_page_id = str(value.get("page_id") or entry.get("id") or "")
                campaign = db.query(ProjectCampaign).join(Project).join(
                    MetaConnection, MetaConnection.id == ProjectCampaign.meta_connection_id,
                ).filter(
                    ProjectCampaign.lead_form_id == str(form_id),
                    ProjectCampaign.platform == "meta",
                    MetaConnection.page_id == event_page_id,
                    MetaConnection.verification_mode == "real",
                    MetaConnection.verification_status == "succeeded",
                    Project.is_demo.is_(False),
                    Project.is_active.is_(True),
                ).first()
                if not campaign:
                    event.status = "ignored"
                    event.error_message = "No active non-Demo campaign matches this form."
                    event.processed_at = datetime.utcnow()
                    db.commit()
                    continue
                details = await _fetch_lead(
                    str(leadgen_id), decrypt_connection_token(campaign.meta_connection)
                )
                fields = _fields(details)
                project = campaign.project
                phone = fields.get("phone_number") or fields.get("phone") or ""
                full_name = fields.get("full_name") or fields.get("name") or "Meta Lead"
                lead = Lead(
                    company_id=project.company_id,
                    project_id=project.id,
                    campaign_id=campaign.id,
                    full_name=full_name,
                    phone=phone,
                    email=fields.get("email"),
                    source="Meta Lead Ads",
                    platform="meta",
                    external_lead_id=str(leadgen_id),
                    preferred_channel="sms" if phone else "email",
                    channel_address=phone or fields.get("email"),
                    consent_status="captured_by_source",
                    consent_captured_at=datetime.utcnow(),
                    meta_form_data={
                        **fields,
                        "leadgen_id": str(leadgen_id),
                        "form_id": str(form_id),
                        "ad_id": str(details.get("ad_id") or value.get("ad_id") or "") or None,
                        "campaign_id": campaign.external_campaign_id,
                        "campaign_name": campaign.name,
                        "campaign_objective": campaign.objective,
                    },
                    agent_status="queued",
                    pipeline_stage="S00_CAPTURE",
                    assigned_sales_user_id=None,
                )
                db.add(lead); db.flush()
                db.add(LeadConsentEvent(
                    lead_id=lead.id, channel="sms", action="consent_captured",
                    source="meta_lead_form", evidence="Captured by configured Meta lead form.",
                ))
                event.status = "processed"
                event.processed_at = datetime.utcnow()
                db.commit()
                background_tasks.add_task(start_live_lead, lead.id)
                accepted += 1
            except (httpx.HTTPError, IntegrityError, ValueError) as exc:
                db.rollback()
                failed = ExternalWebhookEvent(
                    platform="meta",
                    external_event_id=event_id,
                    event_type="leadgen",
                    payload_json={"leadgen_id": leadgen_id, "form_id": form_id},
                    status="failed",
                    error_message=type(exc).__name__,
                    processed_at=datetime.utcnow(),
                )
                try:
                    db.add(failed)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    duplicates += 1
    return {"status": "accepted", "created": accepted, "duplicates": duplicates}
