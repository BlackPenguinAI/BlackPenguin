from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.integrations.twilio_client import public_webhook_url, validate_twilio_signature
from app.modules.system_settings.services import twilio_credentials
from app.modules.sales_crm.models import Lead

from .live_service import process_live_inbound, resolve_inbound_conversation
from .models import ExternalWebhookEvent, OutboundMessage, SalesMessage


router = APIRouter()


def _validate(request: Request, params: dict[str, str], signature: str | None, db: Session):
    config, token = twilio_credentials(db)
    url = public_webhook_url(request.url.path, request.url.query)
    if params.get("AccountSid") != config.account_sid or not validate_twilio_signature(auth_token=token, url=url, params=params, signature=signature):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature.")
    return config


@router.post("/sms")
async def inbound_sms(
    request: Request, background_tasks: BackgroundTasks,
    x_twilio_signature: str | None = Header(None), db: Session = Depends(get_db),
):
    form = await request.form()
    params = {str(key): str(value) for key, value in form.items()}
    config = _validate(request, params, x_twilio_signature, db)
    sid = params.get("MessageSid")
    if not sid or params.get("To") != config.from_phone_number:
        raise HTTPException(status_code=422, detail="Invalid Twilio message payload.")
    if db.query(ExternalWebhookEvent).filter(ExternalWebhookEvent.platform == "twilio", ExternalWebhookEvent.external_event_id == sid).first():
        return Response(content="<Response></Response>", media_type="application/xml")
    conversation = resolve_inbound_conversation(db, to_number=params["To"], from_number=params.get("From", ""))
    event = ExternalWebhookEvent(
        platform="twilio", external_event_id=sid, event_type="incoming_sms",
        payload_json={key: params.get(key) for key in ("MessageSid", "AccountSid", "From", "To", "Body")},
        status="received",
    )
    db.add(event)
    if not conversation:
        event.status = "ignored"; event.error_message = "No unambiguous active provider thread."
        event.processed_at = datetime.utcnow(); db.commit()
        return Response(content="<Response></Response>", media_type="application/xml")
    message = SalesMessage(
        conversation_id=conversation.id, channel="sms", direction="inbound", role="user",
        content=params.get("Body", ""), provider_message_id=sid, status="received",
        metadata_json={"from": params.get("From"), "to": params.get("To")},
    )
    db.add(message); event.status = "processed"; event.processed_at = datetime.utcnow()
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
    if lead: lead.last_interaction_at = datetime.utcnow()
    db.commit(); db.refresh(message)
    if not conversation.is_paused:
        background_tasks.add_task(process_live_inbound, conversation.id, message.id)
    return Response(content="<Response></Response>", media_type="application/xml")


@router.post("/status")
async def message_status(
    request: Request, x_twilio_signature: str | None = Header(None), db: Session = Depends(get_db),
):
    form = await request.form()
    params = {str(key): str(value) for key, value in form.items()}
    _validate(request, params, x_twilio_signature, db)
    sid = params.get("MessageSid")
    message = db.query(SalesMessage).filter(SalesMessage.provider_message_id == sid).first()
    if message:
        message.status = params.get("MessageStatus") or message.status
        message.metadata_json = {**(message.metadata_json or {}), "provider_error_code": params.get("ErrorCode")}
    outbound = db.query(OutboundMessage).filter(OutboundMessage.provider_message_id == sid).first()
    if outbound:
        outbound.status = params.get("MessageStatus") or outbound.status
        outbound.last_error = params.get("ErrorCode") or None
    if message or outbound:
        db.commit()
    return {"status": "accepted"}
