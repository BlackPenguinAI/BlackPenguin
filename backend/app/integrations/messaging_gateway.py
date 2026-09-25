"""Provider-neutral SMS routing used by live conversations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.system_settings.services import (
    get_messaging_routing_config, get_telnyx_config, get_twilio_config, provider_is_ready,
)


def default_provider(db: Session) -> str:
    provider = get_messaging_routing_config(db).default_provider or "twilio"
    return provider if provider in {"twilio", "telnyx"} else "twilio"


def provider_sender(db: Session, provider: str) -> str:
    if provider == "twilio":
        sender = get_twilio_config(db).from_phone_number
    elif provider == "telnyx":
        sender = get_telnyx_config(db).from_phone_number
    else:
        raise HTTPException(status_code=422, detail="Unsupported SMS provider.")
    if not sender:
        raise HTTPException(status_code=409, detail=f"{provider.title()} does not have a sender number configured.")
    return sender


async def send_sms(db: Session, *, provider: str, to: str, body: str) -> dict:
    if provider == "twilio":
        from app.integrations.twilio_client import send_sms as send_twilio_sms
        return await send_twilio_sms(db, to=to, body=body)
    if provider == "telnyx":
        from app.integrations.telnyx_client import send_sms as send_telnyx_sms
        return await send_telnyx_sms(db, to=to, body=body)
    raise HTTPException(status_code=422, detail="Unsupported SMS provider.")


def live_provider(db: Session) -> str | None:
    provider = default_provider(db)
    return provider if provider_is_ready(db, provider) else None
