"""Telnyx Messaging API and signed webhook boundary."""

from __future__ import annotations

import base64
import binascii

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.orm import Session

def _public_key(value: str) -> Ed25519PublicKey:
    cleaned = value.strip()
    if cleaned.startswith("-----BEGIN"):
        key = serialization.load_pem_public_key(cleaned.encode())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Telnyx webhook key must be Ed25519.")
        return key
    try:
        raw = bytes.fromhex(cleaned) if len(cleaned) == 64 else base64.b64decode(cleaned, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid Telnyx webhook public key.") from exc
    if len(raw) != 32:
        raise ValueError("Invalid Telnyx webhook public key.")
    return Ed25519PublicKey.from_public_bytes(raw)


def validate_telnyx_public_key(value: str) -> None:
    """Raise ValueError unless the configured webhook key is Ed25519."""
    _public_key(value)


def telnyx_public_key_bytes(value: str) -> bytes:
    """Return the canonical raw bytes for an Ed25519 public key."""
    return _public_key(value).public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def validate_telnyx_signature(*, public_key: str, payload: bytes, signature: str | None, timestamp: str | None) -> bool:
    if not signature or not timestamp:
        return False
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        _public_key(public_key).verify(signature_bytes, timestamp.encode() + b"|" + payload)
        return True
    except (InvalidSignature, ValueError, binascii.Error):
        return False


async def send_sms(db: Session, *, company_id: str, to: str, body: str) -> dict:
    from app.modules.system_settings.services import get_telnyx_company_config, telnyx_credentials

    platform, api_key = telnyx_credentials(db)
    config = get_telnyx_company_config(db, company_id)
    if not platform.live_sms_enabled or platform.verification_status != "verified":
        raise RuntimeError("Live Telnyx SMS is disabled or not verified.")
    if not config or not config.live_sms_enabled or config.verification_status != "verified":
        raise RuntimeError("Live Telnyx SMS is disabled or not verified.")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.telnyx.com/v2/messages",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": config.from_phone_number,
                "to": to,
                "text": body,
                "messaging_profile_id": config.messaging_profile_id,
            },
        )
        response.raise_for_status()
    data = response.json().get("data") or {}
    return {"sid": data.get("id"), "status": data.get("status") or "queued", "raw": data}
