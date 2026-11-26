"""Provider-neutral SMS/WhatsApp routing used by live conversations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.system_settings.services import (
    get_messaging_routing_config, get_telnyx_company_config, get_twilio_config, provider_is_ready,
)

DESTINATION_PREFIXES = (
    ("+52", "MX"),
    ("+51", "PE"),
    ("+54", "AR"),
    ("+1", "US"),
)

COUNTRY_CHANNELS = {"US": "sms", "PE": "whatsapp", "MX": "whatsapp", "AR": "whatsapp"}


def destination_country_code(phone_number: str | None) -> str | None:
    """Resolve the countries supported by the current messaging policy."""
    if not phone_number:
        return None
    digits = "".join(character for character in phone_number if character.isdigit())
    normalized = f"+{digits}"
    return next((country for prefix, country in DESTINATION_PREFIXES if normalized.startswith(prefix)), None)


def destination_channel(phone_number: str | None) -> str | None:
    """The buyer's destination determines SMS versus WhatsApp, never a fallback."""
    return COUNTRY_CHANNELS.get(destination_country_code(phone_number))


def _channel_is_ready(db: Session, *, company_id: str, channel: str) -> bool:
    config = get_telnyx_company_config(db, company_id)
    if channel == "sms":
        return provider_is_ready(db, default_provider(db), company_id=company_id)
    return bool(
        channel == "whatsapp" and config and config.live_whatsapp_enabled
        and config.whatsapp_verification_status == "verified"
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


def company_live_channel(
    db: Session, *, company_id: str, requested: str | None = None,
    destination_phone: str | None = None,
) -> str | None:
    """Select a ready real channel scoped to Company and destination country.

    A supplied destination is authoritative: even a legacy/requested ``sms``
    value cannot force SMS for a Peru/Mexico/Argentina destination. With no
    destination, keep compatibility for older internal callers (they must
    migrate to passing the destination before activation).
    """
    if destination_phone is not None:
        selected = destination_channel(destination_phone)
        return selected if selected and _channel_is_ready(db, company_id=company_id, channel=selected) else None
    config = get_telnyx_company_config(db, company_id)
    policy = (config.primary_channel or "sms") if config else "sms"
    selected = requested if requested in {"sms", "whatsapp"} else (policy if policy in {"sms", "whatsapp"} else None)
    return selected if selected and _channel_is_ready(db, company_id=company_id, channel=selected) else None


def company_channel_preview(db: Session, *, company_id: str, destination_phone: str) -> dict:
    """Explain the country route without making a simulated delivery."""
    config = get_telnyx_company_config(db, company_id)
    policy = (config.primary_channel or "sms") if config else "sms"
    country = destination_country_code(destination_phone)
    expected = destination_channel(destination_phone)
    channel = company_live_channel(db, company_id=company_id, destination_phone=destination_phone)
    labels = {"US": "United States", "MX": "Mexico", "PE": "Peru", "AR": "Argentina"}
    if not expected:
        detail = "No real messaging route is defined for this destination country. No message will be sent."
    elif not channel:
        detail = f"{expected.upper()} is required for this country but is not verified/enabled for this Company. No message will be sent."
    else:
        detail = f"New conversations to this destination will use live {channel.upper()}."
    return {
        "country_code": country,
        "country_name": labels.get(country),
        "channel": channel or expected,
        "ready": bool(channel),
        "policy": policy,
        "detail": detail,
    }


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
