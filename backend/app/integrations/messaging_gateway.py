"""Provider-neutral SMS/WhatsApp routing used by live conversations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.system_settings.services import (
    get_messaging_routing_config, get_telnyx_company_config, get_twilio_config, provider_is_ready,
)


def default_provider(db: Session) -> str:
    provider = get_messaging_routing_config(db).default_provider or "twilio"
    return provider if provider in {"twilio", "telnyx"} else "twilio"


def provider_sender(db: Session, provider: str, *, company_id: str) -> str:
    if provider == "twilio":
        sender = get_twilio_config(db).from_phone_number
    elif provider == "telnyx":
        config = get_telnyx_company_config(db, company_id)
        sender = config.from_phone_number if config else None
    else:
        raise HTTPException(status_code=422, detail="Unsupported SMS provider.")
    if not sender:
        raise HTTPException(status_code=409, detail=f"{provider.title()} does not have a sender number configured.")
    return sender


def company_live_channel(db: Session, *, company_id: str, requested: str | None = None) -> str | None:
    """Resolve only a verified channel owned by the Company."""
    config = get_telnyx_company_config(db, company_id)
    choices = [requested] if requested else ([config.primary_channel or "sms"] if config else ["sms"])
    for channel in choices:
        if channel == "sms":
            provider = default_provider(db)
            if provider_is_ready(db, provider, company_id=company_id):
                return "sms"
        if channel == "whatsapp" and config and config.live_whatsapp_enabled and config.whatsapp_verification_status == "verified":
            return "whatsapp"
    return None


def channel_sender(db: Session, *, company_id: str, channel: str, provider: str = "telnyx") -> str:
    if channel == "sms":
        return provider_sender(db, provider, company_id=company_id)
    if channel == "whatsapp":
        config = get_telnyx_company_config(db, company_id)
        if config and config.whatsapp_from_phone_number:
            return config.whatsapp_from_phone_number
        raise HTTPException(status_code=409, detail="Telnyx does not have a WhatsApp sender configured for this Company.")
    raise HTTPException(status_code=422, detail="Unsupported messaging channel.")


async def send_sms(db: Session, *, provider: str, company_id: str, to: str, body: str) -> dict:
    if provider == "twilio":
        from app.integrations.twilio_client import send_sms as send_twilio_sms
        return await send_twilio_sms(db, to=to, body=body)
    if provider == "telnyx":
        from app.integrations.telnyx_client import send_sms as send_telnyx_sms
        return await send_telnyx_sms(db, company_id=company_id, to=to, body=body)
    raise HTTPException(status_code=422, detail="Unsupported SMS provider.")


async def send_message(
    db: Session, *, provider: str, channel: str, company_id: str, to: str,
    body: str, use_initial_template: bool = False,
    template_parameters: list[str] | None = None,
) -> dict:
    if channel == "sms":
        return await send_sms(db, provider=provider, company_id=company_id, to=to, body=body)
    if channel == "whatsapp" and provider == "telnyx":
        from app.integrations.telnyx_client import send_whatsapp
        return await send_whatsapp(
            db, company_id=company_id, to=to, body=body,
            use_initial_template=use_initial_template,
            template_parameters=template_parameters,
        )
    raise HTTPException(status_code=422, detail="Unsupported provider/channel combination.")


def live_provider(db: Session, *, company_id: str) -> str | None:
    provider = default_provider(db)
    return provider if provider_is_ready(db, provider, company_id=company_id) else None
