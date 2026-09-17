"""Keyless Firebase Admin bridge intended for Google Cloud Run."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import firebase_admin
from fastapi import FastAPI, HTTPException, Request
from firebase_admin import auth, firestore


EXPECTED_PROJECT_ID = os.environ["FIREBASE_PROJECT_ID"]
SHARED_SECRET = os.environ["BRIDGE_SHARED_SECRET"]
MAX_CLOCK_SKEW_SECONDS = 300

firebase_admin.initialize_app(options={"projectId": EXPECTED_PROJECT_ID})
app = FastAPI(title="Black Penguin Firebase Admin Bridge", docs_url=None, redoc_url=None)
MAIL_COLLECTION = os.getenv("FIRESTORE_MAIL_COLLECTION", "mail").strip() or "mail"


def _verify_signature(body: bytes, timestamp: str | None, signature: str | None) -> None:
    try:
        issued_at = int(timestamp or "")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid request signature.") from exc
    if abs(int(time.time()) - issued_at) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Expired request signature.")
    expected = hmac.new(
        SHARED_SECRET.encode("utf-8"),
        str(issued_at).encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid request signature.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mail_collection": MAIL_COLLECTION}


async def _trusted_payload(request: Request) -> dict:
    body = await request.body()
    _verify_signature(body, request.headers.get("X-BlackPenguin-Timestamp"), request.headers.get("X-BlackPenguin-Signature"))
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON payload.") from exc
    if payload.get("project_id") != EXPECTED_PROJECT_ID:
        raise HTTPException(status_code=403, detail="Firebase project mismatch.")
    return payload


@app.post("/mail/enqueue")
async def enqueue_mail(request: Request) -> dict[str, str]:
    payload = await _trusted_payload(request)
    if payload.get("mail_collection", MAIL_COLLECTION) != MAIL_COLLECTION:
        raise HTTPException(status_code=409, detail="Configured Firestore mail collection does not match the bridge.")
    document_id = str(payload.get("document_id") or "").strip()
    recipients = payload.get("to") or []
    message = payload.get("message") or {}
    if not document_id or len(document_id) > 255 or not isinstance(recipients, list) or not recipients:
        raise HTTPException(status_code=422, detail="A valid document ID and recipient list are required.")
    if not message.get("subject") or not (message.get("text") or message.get("html")):
        raise HTTPException(status_code=422, detail="Email subject and content are required.")
    document = {"to": recipients, "message": message}
    for key in ("from", "replyTo", "cc", "bcc", "headers"):
        if payload.get(key):
            document[key] = payload[key]
    reference = firestore.client().collection(MAIL_COLLECTION).document(document_id)
    snapshot = reference.get()
    if not snapshot.exists:
        reference.create(document)
        return {"status": "queued", "document_id": document_id}
    existing = snapshot.to_dict() or {}
    return {"status": str((existing.get("delivery") or {}).get("state") or "queued").lower(), "document_id": document_id}


@app.post("/mail/status")
async def mail_status(request: Request) -> dict[str, str]:
    payload = await _trusted_payload(request)
    if payload.get("mail_collection", MAIL_COLLECTION) != MAIL_COLLECTION:
        raise HTTPException(status_code=409, detail="Configured Firestore mail collection does not match the bridge.")
    document_id = str(payload.get("document_id") or "").strip()
    snapshot = firestore.client().collection(MAIL_COLLECTION).document(document_id).get()
    if not snapshot.exists:
        return {"status": "not_found", "document_id": document_id}
    delivery = (snapshot.to_dict() or {}).get("delivery") or {}
    result = {"status": str(delivery.get("state") or "queued").lower(), "document_id": document_id}
    if delivery.get("error"):
        result["error"] = str(delivery["error"])[:300]
    return result


@app.post("/users/delete")
async def delete_user(request: Request) -> dict[str, str]:
    payload = await _trusted_payload(request)

    uid = str(payload.get("uid") or "").strip()
    email = str(payload.get("email") or "").strip().casefold()
    if not uid and not email:
        raise HTTPException(status_code=422, detail="A Firebase UID or email is required.")

    try:
        if not uid:
            uid = auth.get_user_by_email(email).uid
        auth.delete_user(uid)
    except auth.UserNotFoundError:
        return {"status": "not_found"}
    except Exception as exc:
        # Return a stable, non-sensitive code to the caller. Detailed provider
        # diagnostics remain in Cloud Run logs.
        raise HTTPException(
            status_code=502,
            detail="Firebase Admin deletion failed.",
            headers={"X-Error-Code": type(exc).__name__},
        ) from exc
    return {"status": "deleted"}
