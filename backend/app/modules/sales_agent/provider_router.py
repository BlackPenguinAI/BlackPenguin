"""Authenticated Twilio and Telnyx messaging webhooks."""

from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.integrations.telnyx_client import validate_telnyx_signature
from app.integrations.twilio_client import public_webhook_url, validate_twilio_signature
from app.modules.sales_crm.models import Lead
from app.modules.system_settings.services import (
    telnyx_company_for_number, telnyx_company_for_whatsapp_number,
    telnyx_credentials, twilio_credentials,
)

from .live_service import process_live_inbound, resolve_inbound_conversation
from .models import ExternalWebhookEvent, OutboundMessage, SalesConversation, SalesMessage


twilio_router = APIRouter()
telnyx_router = APIRouter()


def _record_inbound(
    db: Session, *, provider: str, event_id: str, to_number: str, from_number: str,
    body: str, payload: dict, background_tasks: BackgroundTasks,
    expected_company_id: str | None = None, provider_message_id: str | None = None,
    channel: str = "sms", message_type: str = "text",
):
    if db.query(ExternalWebhookEvent).filter(
        ExternalWebhookEvent.platform == provider,
        ExternalWebhookEvent.external_event_id == event_id,
    ).first():
        return
    conversation = resolve_inbound_conversation(
        db, provider=provider, channel=channel, to_number=to_number, from_number=from_number,
    )
    event = ExternalWebhookEvent(platform=provider, external_event_id=event_id, event_type=f"incoming_{channel}", payload_json=payload, status="received")
    db.add(event)
    if not conversation or (expected_company_id and conversation.company_id != expected_company_id):
        event.status = "ignored"; event.error_message = "No unambiguous active provider thread."
        event.processed_at = datetime.utcnow(); db.commit(); return
    normalized_body = body.strip()
    content_supported = bool(normalized_body)
    display_body = normalized_body or f"[Unsupported {channel.upper()} {message_type} message]"
    message = SalesMessage(
        conversation_id=conversation.id, channel=channel, direction="inbound", role="user",
        content=display_body, provider_message_id=provider_message_id or event_id, status="received",
        metadata_json={
            "provider": provider, "from": from_number, "to": to_number,
            "message_type": message_type, "content_supported": content_supported,
        },
    )
    db.add(message)
    event.status = "processed" if content_supported else "ignored"
    event.error_message = None if content_supported else "Inbound content was empty or unsupported; agent execution skipped."
    event.processed_at = datetime.utcnow()
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
    if lead:
        lead.last_interaction_at = datetime.utcnow()
    db.commit(); db.refresh(message)
    if content_supported and not conversation.is_paused:
        background_tasks.add_task(process_live_inbound, conversation.id, message.id)


def _apply_status(db: Session, *, provider: str, message_id: str, status: str, error: str | None = None):
    conversation_ids = db.query(SalesConversation.id).filter(SalesConversation.provider == provider)
    message = db.query(SalesMessage).filter(SalesMessage.provider_message_id == message_id, SalesMessage.conversation_id.in_(conversation_ids)).first()
    outbound = db.query(OutboundMessage).filter(OutboundMessage.provider == provider, OutboundMessage.provider_message_id == message_id).first()
    if message:
        message.status = status
        message.metadata_json = {**(message.metadata_json or {}), "provider_error": error}
    if outbound:
        outbound.status = status; outbound.last_error = error
    if message or outbound:
        db.commit()


def _status_from_telnyx(event_type: str, payload: dict) -> str:
    """Return the delivery state, not Telnyx's generic event lifecycle name."""
    destinations = payload.get("to") or []
    destination_statuses = [
        str(item.get("status") or "").strip().lower()
        for item in destinations if isinstance(item, dict) and item.get("status")
    ]
    if destination_statuses:
        return destination_statuses[0]
    for prefix in ("whatsapp.message.", "message."):
        if event_type.startswith(prefix):
            return event_type.removeprefix(prefix) or "queued"
    return event_type or "queued"


def _telnyx_phone(value) -> str:
    if isinstance(value, dict):
        return str(value.get("phone_number") or value.get("number") or "")
    return str(value or "")


def _telnyx_channel(payload: dict) -> str:
    marker = " ".join(str(payload.get(key) or "") for key in ("type", "record_type", "channel")).casefold()
    return "whatsapp" if "whatsapp" in marker or isinstance(payload.get("whatsapp_message"), dict) else "sms"


def _telnyx_text(payload: dict, channel: str) -> str:
    if channel == "sms":
        return str(payload.get("text") or "")
    # The unified Telnyx webhook schema uses payload.body for WhatsApp and RCS.
    # Keep the preview-era whatsapp_message shape as a compatibility fallback.
    body = payload.get("body") or {}
    if isinstance(body, dict):
        text = body.get("text")
        if isinstance(text, dict):
            value = text.get("body")
            if value is not None:
                return str(value)
        elif text is not None:
            return str(text)
    message = payload.get("whatsapp_message") or {}
    text = message.get("text") if isinstance(message, dict) else None
    if isinstance(text, dict):
        return str(text.get("body") or "")
    return str(text or payload.get("text") or "")


def _telnyx_message_type(payload: dict, channel: str) -> str:
    if channel == "sms":
        return "text"
    body = payload.get("body")
    if isinstance(body, dict) and body.get("type"):
        return str(body["type"]).strip().lower()
    message = payload.get("whatsapp_message")
    if isinstance(message, dict) and message.get("type"):
        return str(message["type"]).strip().lower()
    return "unknown"


def _validate_twilio(request: Request, params: dict[str, str], signature: str | None, db: Session):
    config, token = twilio_credentials(db)
    url = public_webhook_url(request.url.path, request.url.query)
    if params.get("AccountSid") != config.account_sid or not validate_twilio_signature(auth_token=token, url=url, params=params, signature=signature):
        raise HTTPException(status_code=401, detail="Invalid Twilio signature.")
    return config


@twilio_router.post("/sms")
async def twilio_inbound_sms(request: Request, background_tasks: BackgroundTasks, x_twilio_signature: str | None = Header(None), db: Session = Depends(get_db)):
    form = await request.form()
    params = {str(key): str(value) for key, value in form.items()}
    config = _validate_twilio(request, params, x_twilio_signature, db)
    sid = params.get("MessageSid")
    if not sid or params.get("To") != config.from_phone_number:
        raise HTTPException(status_code=422, detail="Invalid Twilio message payload.")
    _record_inbound(db, provider="twilio", event_id=sid, to_number=params["To"], from_number=params.get("From", ""), body=params.get("Body", ""), payload={key: params.get(key) for key in ("MessageSid", "AccountSid", "From", "To", "Body")}, background_tasks=background_tasks)
    return Response(content="<Response></Response>", media_type="application/xml")


@twilio_router.post("/status")
async def twilio_message_status(request: Request, x_twilio_signature: str | None = Header(None), db: Session = Depends(get_db)):
    form = await request.form()
    params = {str(key): str(value) for key, value in form.items()}
    _validate_twilio(request, params, x_twilio_signature, db)
    if params.get("MessageSid"):
        _apply_status(db, provider="twilio", message_id=params["MessageSid"], status=params.get("MessageStatus") or "queued", error=params.get("ErrorCode"))
    return {"status": "accepted"}


@telnyx_router.post("/messaging")
async def telnyx_messaging_webhook(request: Request, background_tasks: BackgroundTasks, telnyx_signature_ed25519: str | None = Header(None), telnyx_timestamp: str | None = Header(None), db: Session = Depends(get_db)):
    platform, _ = telnyx_credentials(db)
    body = await request.body()
    try:
        timestamp = int(telnyx_timestamp or "")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Telnyx timestamp.") from exc
    if abs(int(time.time()) - timestamp) > 300:
        raise HTTPException(status_code=401, detail="Expired Telnyx webhook.")
    if not validate_telnyx_signature(public_key=platform.webhook_public_key, payload=body, signature=telnyx_signature_ed25519, timestamp=telnyx_timestamp):
        raise HTTPException(status_code=401, detail="Invalid Telnyx signature.")
    try:
        envelope = json.loads(body)
        data = envelope["data"]; payload = data["payload"]
        event_id = str(data["id"]); event_type = str(data["event_type"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Telnyx webhook payload.") from exc
    if db.query(ExternalWebhookEvent).filter(
        ExternalWebhookEvent.platform == "telnyx",
        ExternalWebhookEvent.external_event_id == event_id,
    ).first():
        return {"status": "accepted"}
    if event_type in {"message.received", "whatsapp.message.received"}:
        channel = _telnyx_channel(payload)
        destinations = payload.get("to") or []
        destination = destinations[0] if isinstance(destinations, list) and destinations else destinations
        to_number = _telnyx_phone(destination)
        from_number = _telnyx_phone(payload.get("from"))
        message_id = str(payload.get("id") or event_id)
        company_config = (
            telnyx_company_for_whatsapp_number(db, to_number)
            if channel == "whatsapp" else telnyx_company_for_number(db, to_number)
        )
        if not company_config or not from_number:
            raise HTTPException(status_code=422, detail="Invalid Telnyx message payload.")
        _record_inbound(
            db, provider="telnyx", event_id=event_id, to_number=to_number,
            from_number=from_number, body=_telnyx_text(payload, channel),
            payload=envelope, background_tasks=background_tasks,
            expected_company_id=company_config.company_id,
            provider_message_id=message_id,
            channel=channel,
            message_type=_telnyx_message_type(payload, channel),
        )
    elif event_type.startswith("message.") or event_type.startswith("whatsapp.message."):
        event = ExternalWebhookEvent(
            platform="telnyx", external_event_id=event_id,
            event_type=event_type, payload_json=envelope,
            status="processed", processed_at=datetime.utcnow(),
        )
        db.add(event)
        message_id = str(payload.get("id") or "")
        if message_id:
            errors = payload.get("errors") or []
            error = str(errors[0].get("detail") or errors[0].get("code")) if errors else None
            _apply_status(
                db, provider="telnyx", message_id=message_id,
                status=_status_from_telnyx(event_type, payload), error=error,
            )
        else:
            db.commit()
    return {"status": "accepted"}


router = twilio_router
