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
from app.modules.system_settings import services as system_settings


router = APIRouter()


def _valid_signature(body: bytes, signature: str | None, app_secret: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


async def _fetch_lead(leadgen_id: str, access_token: str, graph_api_version: str) -> dict:
    url = f"https://graph.facebook.com/{graph_api_version}/{leadgen_id}"
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


def _resolve_campaign(
    db: Session, *, page_id: str, form_id: str, ad_id: str | None,
) -> tuple[ProjectCampaign | None, str | None]:
    """Resolve a Meta route deterministically; never pick an arbitrary tenant Project."""
    candidates = db.query(ProjectCampaign).join(Project).join(
        MetaConnection, MetaConnection.id == ProjectCampaign.meta_connection_id,
    ).filter(
        ProjectCampaign.lead_form_id == form_id,
        ProjectCampaign.platform == "meta",
        MetaConnection.page_id == page_id,
        MetaConnection.verification_mode == "real",
        MetaConnection.verification_status == "succeeded",
        Project.is_demo.is_(False),
        Project.is_active.is_(True),
    ).all()
    if ad_id:
        exact = [item for item in candidates if item.external_ad_id == ad_id]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return None, "Ambiguous Meta route: Page, Form, and Ad are assigned more than once."
    generic = [item for item in candidates if not item.external_ad_id]
    if len(generic) == 1:
        return generic[0], None
    if not ad_id and len(candidates) == 1:
        return candidates[0], None
    if ad_id and candidates:
        return None, "No Project mapping matches the incoming Ad ID."
    if candidates:
        return None, "Ambiguous Meta route: add the Ad ID to every Project mapping that shares this Page and Form."
    return None, "No active non-Demo campaign matches this Page and Form."


@router.get("/meta")
def verify(
    mode: str = Query(..., alias="hub.mode"),
    token: str = Query(..., alias="hub.verify_token"),
    challenge: str = Query(..., alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    expected = system_settings.meta_webhook_verify_token(db) or settings.META_VERIFY_TOKEN
    if mode == "subscribe" and hmac.compare_digest(token, expected):
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
    try:
        meta_config, app_secret = system_settings.meta_platform_credentials(db, require_enabled=False)
        graph_api_version = meta_config.graph_api_version
    except HTTPException:
        app_secret = settings.META_APP_SECRET
        graph_api_version = settings.META_API_VERSION
    if not app_secret or not _valid_signature(body, x_hub_signature_256, app_secret):
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
                webhook_ad_id = str(value.get("ad_id") or "") or None
                campaign, route_error = _resolve_campaign(
                    db, page_id=event_page_id, form_id=str(form_id), ad_id=webhook_ad_id,
                )
                if not campaign:
                    event.status = "ignored"
                    event.error_message = route_error
                    event.processed_at = datetime.utcnow()
                    db.commit()
                    continue
                details = await _fetch_lead(
                    str(leadgen_id), decrypt_connection_token(campaign.meta_connection), graph_api_version,
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
