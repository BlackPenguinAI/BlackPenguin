"""Keyless Firebase Admin bridge intended for Google Cloud Run."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import firebase_admin
from fastapi import FastAPI, HTTPException, Request
from firebase_admin import auth


EXPECTED_PROJECT_ID = os.environ["FIREBASE_PROJECT_ID"]
SHARED_SECRET = os.environ["BRIDGE_SHARED_SECRET"]
MAX_CLOCK_SKEW_SECONDS = 300

firebase_admin.initialize_app(options={"projectId": EXPECTED_PROJECT_ID})
app = FastAPI(title="Black Penguin Firebase Admin Bridge", docs_url=None, redoc_url=None)


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
    return {"status": "ok"}


@app.post("/users/delete")
async def delete_user(request: Request) -> dict[str, str]:
    body = await request.body()
    _verify_signature(
        body,
        request.headers.get("X-BlackPenguin-Timestamp"),
        request.headers.get("X-BlackPenguin-Signature"),
    )
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON payload.") from exc
    if payload.get("project_id") != EXPECTED_PROJECT_ID:
        raise HTTPException(status_code=403, detail="Firebase project mismatch.")

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
