"""Authenticated boundary for privileged Firebase user deletion."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx
from fastapi import HTTPException

from app.core.config import settings


logger = logging.getLogger(__name__)


def admin_deletion_is_configured() -> bool:
    """Return whether privileged deletion can be attempted from this API."""
    return bool(
        settings.FIREBASE_ADMIN_BRIDGE_URL
        and settings.FIREBASE_ADMIN_BRIDGE_SECRET
    )


def email_bridge_is_configured() -> bool:
    """Return whether the email bridge can be reached from this API."""
    return bool(
        settings.FIREBASE_ADMIN_BRIDGE_URL
        and settings.FIREBASE_ADMIN_BRIDGE_SECRET
    )


def ensure_admin_deletion_ready() -> None:
    if not admin_deletion_is_configured():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FIREBASE_ADMIN_DELETE_UNAVAILABLE",
                "message": (
                    "Firebase administrative deletion is not configured. "
                    "Configure the keyless Firebase Admin bridge, or confirm that the "
                    "Company identities were already removed manually from Firebase."
                ),
                "can_confirm_manual_cleanup": True,
            },
        )


def ensure_email_bridge_ready() -> None:
    if not email_bridge_is_configured():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FIREBASE_ADMIN_EMAIL_UNAVAILABLE",
                "message": (
                    "The Firebase Admin bridge for appointment email is not configured. "
                    "Set FIREBASE_ADMIN_BRIDGE_URL and FIREBASE_ADMIN_BRIDGE_SECRET, "
                    "then redeploy the API and worker."
                ),
            },
        )


def _signed_headers(body: bytes, timestamp: str) -> dict[str, str]:
    signature = hmac.new(
        settings.FIREBASE_ADMIN_BRIDGE_SECRET.encode("utf-8"),
        timestamp.encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-BlackPenguin-Timestamp": timestamp,
        "X-BlackPenguin-Signature": signature,
    }


def _bridge_post(path: str, payload: dict) -> dict:
    ensure_email_bridge_ready()
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    try:
        response = httpx.post(
            settings.FIREBASE_ADMIN_BRIDGE_URL.rstrip("/") + path,
            content=body,
            headers=_signed_headers(body, timestamp),
            timeout=settings.FIREBASE_ADMIN_BRIDGE_TIMEOUT_SECONDS,
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Firebase Admin bridge is temporarily unavailable.") from exc
    if response.is_error:
        raise RuntimeError(str(data.get("detail") or "Firebase Admin bridge rejected the request."))
    return data


def enqueue_email(*, project_id: str, document_id: str, recipient: str, subject: str,
                  text: str, html: str, attachments: list[dict] | None = None,
                  from_email: str | None = None, reply_to: str | None = None,
                  mail_collection: str = "mail") -> dict:
    payload = {
        "project_id": project_id,
        "document_id": document_id,
        "mail_collection": mail_collection,
        "to": [recipient],
        "message": {"subject": subject, "text": text, "html": html, "attachments": attachments or []},
    }
    if from_email:
        payload["from"] = from_email
    if reply_to:
        payload["replyTo"] = reply_to
    return _bridge_post("/mail/enqueue", payload)


def email_status(*, project_id: str, document_id: str, mail_collection: str = "mail") -> dict:
    return _bridge_post("/mail/status", {"project_id": project_id, "document_id": document_id, "mail_collection": mail_collection})


def delete_identity(*, project_id: str, firebase_uid: str | None, email: str) -> str:
    """Delete one identity idempotently; a missing identity is successful."""
    ensure_admin_deletion_ready()
    payload = {
        "project_id": project_id,
        "uid": firebase_uid,
        "email": email.strip().casefold(),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    try:
        response = httpx.post(
            settings.FIREBASE_ADMIN_BRIDGE_URL.rstrip("/") + "/users/delete",
            content=body,
            headers=_signed_headers(body, timestamp),
            timeout=settings.FIREBASE_ADMIN_BRIDGE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.error(
            "Firebase Admin bridge transport failure email=%s has_uid=%s exception_type=%s",
            email, bool(firebase_uid), type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Firebase administrative deletion is temporarily unavailable. The Company was not deleted.",
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        logger.error(
            "Firebase Admin bridge invalid response email=%s has_uid=%s http_status=%s",
            email, bool(firebase_uid), response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Firebase administrative deletion returned an invalid response. The Company was not deleted.",
        ) from exc

    if response.is_error:
        error_code = str(
            response.headers.get("X-Error-Code")
            or data.get("error_code")
            or "FIREBASE_ADMIN_DELETE_FAILED"
        )
        logger.error(
            "Firebase Admin bridge rejected deletion email=%s has_uid=%s http_status=%s error_code=%s",
            email, bool(firebase_uid), response.status_code, error_code,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Firebase could not delete a Company identity ({error_code}). The Company remains disabled for retry.",
        )

    result = str(data.get("status") or "deleted")
    logger.info(
        "Firebase identity deletion completed email=%s has_uid=%s result=%s",
        email, bool(firebase_uid), result,
    )
    return result
