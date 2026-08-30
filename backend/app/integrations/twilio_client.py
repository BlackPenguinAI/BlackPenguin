"""Twilio Programmable Messaging transport boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.system_settings.services import twilio_credentials


def validate_twilio_signature(*, auth_token: str, url: str, params: dict[str, str], signature: str | None) -> bool:
    if not signature:
        return False
    payload = url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
    expected = base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(signature, expected)


def public_webhook_url(path: str, query: str = "") -> str:
    url = f"{settings.PUBLIC_APP_URL.rstrip('/')}{path}"
    return f"{url}?{query}" if query else url


async def send_sms(
    db: Session, *, to: str, body: str, status_callback_path: str = "/api/v1/webhooks/twilio/status",
) -> dict:
    config, token = twilio_credentials(db)
    if not config.live_sms_enabled or config.verification_status != "verified":
        raise RuntimeError("Live Twilio SMS is disabled or not verified.")
    payload = {
        "To": to,
        "From": config.from_phone_number,
        "Body": body,
        "StatusCallback": public_webhook_url(status_callback_path),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.account_sid}/Messages.json",
            content=urlencode(payload),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(config.account_sid, token),
        )
        response.raise_for_status()
        return response.json()
