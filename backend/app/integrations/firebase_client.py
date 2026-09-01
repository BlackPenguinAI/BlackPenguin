"""Firebase Authentication REST boundary.

The Web API key is intentionally sufficient for these end-user operations.
PostgreSQL remains authoritative for tenant membership, roles, project access
and suspension, so a Firebase identity never grants application access alone.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.system_settings.models import FirebaseConfig


IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirebaseIdentity:
    uid: str


def _configuration(db: Session, *, require_enabled: bool = True) -> FirebaseConfig:
    config = db.query(FirebaseConfig).first()
    if not config or not config.project_id or not config.api_key:
        logger.error(
            "Firebase configuration unavailable configured=%s project_id_present=%s api_key_present=%s",
            bool(config), bool(config and config.project_id), bool(config and config.api_key),
        )
        raise HTTPException(status_code=409, detail="Firebase Authentication is not configured by Black Penguin.")
    if require_enabled and not config.is_enabled:
        logger.error(
            "Firebase configuration disabled project_id=%s verification_status=%s",
            config.project_id, config.verification_status,
        )
        raise HTTPException(status_code=409, detail="Firebase Authentication is not enabled by Black Penguin.")
    return config


def ensure_firebase_ready(db: Session) -> FirebaseConfig:
    config = _configuration(db)
    if config.verification_status != "verified":
        logger.error(
            "Firebase configuration not verified project_id=%s verification_status=%s",
            config.project_id, config.verification_status,
        )
        raise HTTPException(status_code=409, detail="Verify Firebase Authentication before inviting users.")
    return config


def _firebase_error(code: str) -> HTTPException:
    normalized = code.split(" : ", 1)[0]
    if normalized in {"INVALID_PASSWORD", "EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS", "INVALID_ID_TOKEN", "TOKEN_EXPIRED"}:
        return HTTPException(status_code=401, detail=normalized)
    if normalized == "EMAIL_EXISTS":
        return HTTPException(status_code=409, detail=normalized)
    return HTTPException(status_code=422, detail=normalized)


def _request(config: FirebaseConfig, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{IDENTITY_TOOLKIT}/{endpoint}", params={"key": config.api_key},
            json=payload, timeout=15.0,
        )
        data = response.json()
    except httpx.HTTPError as exc:
        # Do not log the exception string: httpx may include the request URL,
        # whose query string contains the Firebase Web API key.
        logger.error(
            "Firebase REST transport failure endpoint=%s project_id=%s exception_type=%s",
            endpoint, config.project_id, type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Firebase Authentication is temporarily unavailable.") from exc
    except ValueError as exc:
        logger.error(
            "Firebase REST invalid JSON response endpoint=%s project_id=%s http_status=%s",
            endpoint, config.project_id, response.status_code,
        )
        raise HTTPException(status_code=502, detail="Firebase Authentication is temporarily unavailable.") from exc
    if response.is_error:
        error_code = str(data.get("error", {}).get("message", "FIREBASE_REQUEST_FAILED")).split(" : ", 1)[0]
        logger.error(
            "Firebase REST request rejected endpoint=%s project_id=%s http_status=%s error_code=%s",
            endpoint, config.project_id, response.status_code, error_code,
        )
        raise _firebase_error(error_code)
    return data


def create_identity(db: Session, *, email: str, password: str, display_name: str = "") -> FirebaseIdentity:
    config = ensure_firebase_ready(db)
    data = _request(config, "accounts:signUp", {
        "email": email, "password": password, "returnSecureToken": True,
    })
    return FirebaseIdentity(uid=str(data["localId"]))


def recover_identity(db: Session, *, email: str, password: str) -> FirebaseIdentity:
    data = sign_in_with_password(db, email, password)
    return FirebaseIdentity(uid=str(data["localId"]))


def update_password(db: Session, *, id_token: str, password: str) -> None:
    config = _configuration(db)
    _request(config, "accounts:update", {
        "idToken": id_token, "password": password, "returnSecureToken": True,
    })


def _continue_url(config: FirebaseConfig, **parameters: str) -> str:
    parts = urlsplit(config.action_handler_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(parameters)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def send_email_sign_in_link(db: Session, email: str, *, invitation_state: str) -> None:
    """Send an invitation that must be completed inside Black Penguin."""
    config = _configuration(db)
    _request(config, "accounts:sendOobCode", {
        "requestType": "EMAIL_SIGNIN",
        "email": email,
        "continueUrl": _continue_url(config, state=invitation_state),
        "canHandleCodeInApp": True,
    })


def sign_in_with_email_link(db: Session, *, email: str, oob_code: str) -> dict[str, Any]:
    config = _configuration(db)
    return _request(config, "accounts:signInWithEmailLink", {
        "email": email,
        "oobCode": oob_code,
    })


def send_password_reset_email(db: Session, email: str) -> None:
    """Send recovery for an active account; never use this as an invitation."""
    config = _configuration(db)
    _request(config, "accounts:sendOobCode", {
        "requestType": "PASSWORD_RESET", "email": email,
        "continueUrl": _continue_url(config, passwordReset="complete"),
    })


def verify_password_action_code(db: Session, code: str) -> str:
    config = _configuration(db)
    data = _request(config, "accounts:resetPassword", {"oobCode": code})
    return str(data["email"]).strip().casefold()


def confirm_password_action(db: Session, code: str, password: str) -> str:
    config = _configuration(db)
    data = _request(config, "accounts:resetPassword", {"oobCode": code, "newPassword": password})
    return str(data["email"]).strip().casefold()


def sign_in_with_password(db: Session, email: str, password: str) -> dict[str, Any]:
    config = _configuration(db)
    return _request(config, "accounts:signInWithPassword", {
        "email": email, "password": password, "returnSecureToken": True,
    })


def verify_id_token(db: Session, token: str) -> dict[str, Any]:
    config = _configuration(db)
    data = _request(config, "accounts:lookup", {"idToken": token})
    users = data.get("users") or []
    if not users or not users[0].get("localId"):
        raise HTTPException(status_code=401, detail="Invalid Firebase identity token.")
    identity = dict(users[0])
    identity["uid"] = identity["localId"]
    return identity


def verify_configuration(db: Session) -> None:
    """Validate Web API configuration without creating or modifying a user."""
    config = _configuration(db, require_enabled=False)
    _request(config, "accounts:createAuthUri", {
        "identifier": "firebase-check@invalid.blackpenguin.ai",
        "continueUri": config.action_handler_url,
    })
