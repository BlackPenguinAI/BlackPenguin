"""Google Calendar OAuth, FreeBusy and event transport."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.secret_store import decrypt_secret, encrypt_secret
from app.modules.system_settings.services import google_calendar_credentials

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.freebusy"]


def authorization_url(db: Session, state: str, login_hint: str | None = None) -> str:
    config, _ = google_calendar_credentials(db)
    params = {"client_id": config.client_id, "redirect_uri": config.redirect_uri, "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline", "include_granted_scopes": "true", "prompt": "consent", "state": state}
    if login_hint: params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(db: Session, code: str) -> dict:
    config, secret = google_calendar_credentials(db)
    response = httpx.post(TOKEN_URL, data={"code": code, "client_id": config.client_id, "client_secret": secret, "redirect_uri": config.redirect_uri, "grant_type": "authorization_code"}, timeout=20.0)
    response.raise_for_status(); return response.json()


def _access_token(db: Session, connection) -> str:
    token = decrypt_secret(connection.access_token_ciphertext)
    if token and connection.token_expires_at and connection.token_expires_at > datetime.utcnow() + timedelta(minutes=2): return token
    refresh = decrypt_secret(connection.refresh_token_ciphertext)
    if not refresh: raise RuntimeError("Google Calendar refresh token is unavailable.")
    config, secret = google_calendar_credentials(db)
    response = httpx.post(TOKEN_URL, data={"client_id": config.client_id, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=20.0)
    response.raise_for_status(); data = response.json()
    connection.access_token_ciphertext = encrypt_secret(data["access_token"])
    connection.token_expires_at = datetime.utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)))
    connection.status = "connected"; connection.last_error = None; db.flush()
    return data["access_token"]


def calendar_busy_ranges(db: Session, connection, *, starts_at: datetime, ends_at: datetime) -> list[tuple[datetime, datetime]]:
    if connection.status != "connected": return []
    try:
        token = _access_token(db, connection)
        response = httpx.post(f"{CALENDAR_API}/freeBusy", headers={"Authorization": f"Bearer {token}"}, json={"timeMin": starts_at.replace(tzinfo=timezone.utc).isoformat(), "timeMax": ends_at.replace(tzinfo=timezone.utc).isoformat(), "items": [{"id": connection.calendar_id or "primary"}]}, timeout=15.0)
        response.raise_for_status(); busy = response.json().get("calendars", {}).get(connection.calendar_id or "primary", {}).get("busy", [])
        connection.last_synced_at = datetime.utcnow(); connection.last_error = None; db.flush()
        return [
            (
                datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None),
                datetime.fromisoformat(item["end"].replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None),
            )
            for item in busy
        ]
    except (httpx.HTTPError, RuntimeError, HTTPException) as exc:
        connection.last_error = type(exc).__name__; db.flush()
        # Fail closed: a disconnected external calendar must never cause a
        # double booking just because FreeBusy is temporarily unavailable.
        return [(starts_at, ends_at)]


def is_calendar_free(db: Session, connection, *, starts_at: datetime, ends_at: datetime) -> bool:
    return not calendar_busy_ranges(db, connection, starts_at=starts_at, ends_at=ends_at)


def create_calendar_event_for_connection(db: Session, connection, *, title: str, description: str, location: str, start_time: datetime, end_time: datetime, timezone_name: str, attendee_email: str | None) -> dict:
    token = _access_token(db, connection)
    body = {"summary": title, "description": description, "location": location, "start": {"dateTime": start_time.replace(tzinfo=timezone.utc).isoformat(), "timeZone": timezone_name}, "end": {"dateTime": end_time.replace(tzinfo=timezone.utc).isoformat(), "timeZone": timezone_name}, "reminders": {"useDefault": False, "overrides": [{"method": "email", "minutes": 1440}, {"method": "popup", "minutes": 60}]}}
    if attendee_email: body["attendees"] = [{"email": attendee_email}]
    response = httpx.post(f"{CALENDAR_API}/calendars/{connection.calendar_id or 'primary'}/events", params={"sendUpdates": "all"}, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=20.0)
    response.raise_for_status(); return response.json()


def create_calendar_event(calendar_id: str, title: str, start_time: datetime, attendee_email: str) -> str:
    """Compatibility adapter for legacy Broker records."""
    return f"legacy_calendar_pending_{uuid.uuid4().hex[:12]}"
