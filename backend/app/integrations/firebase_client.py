"""Firebase Authentication boundary.

Firebase owns credentials and email action codes. PostgreSQL remains the source
of truth for tenant membership, roles, project access and account state.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.secret_store import decrypt_secret
from app.modules.system_settings.models import FirebaseConfig


IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"
_firebase_apps: dict[str, Any] = {}


def _configuration(db: Session, *, require_enabled: bool = True) -> FirebaseConfig:
    config = db.query(FirebaseConfig).first()
    if not config or not config.project_id or not config.api_key:
        raise HTTPException(status_code=409, detail="Firebase Authentication is not configured by Black Penguin.")
    if require_enabled and not config.is_enabled:
        raise HTTPException(status_code=409, detail="Firebase Authentication is not enabled by Black Penguin.")
    return config


def _service_account(config: FirebaseConfig) -> dict[str, Any]:
    try:
        raw = decrypt_secret(config.service_account_ciphertext)
        value = json.loads(raw or "")
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=409, detail="The stored Firebase service account cannot be decrypted or parsed.") from exc
    if value.get("project_id") != config.project_id or not value.get("private_key") or not value.get("client_email"):
        raise HTTPException(status_code=409, detail="Firebase service account does not match the configured Project ID.")
    return value


def _initialize_app(config: FirebaseConfig):
    service_account = _service_account(config)
    cache_key = f"{config.id}:{config.updated_at.isoformat() if config.updated_at else 'initial'}"
    if cache_key in _firebase_apps:
        return _firebase_apps[cache_key]
    try:
        import firebase_admin
        from firebase_admin import credentials
        app = firebase_admin.initialize_app(
            credentials.Certificate(service_account),
            {"projectId": config.project_id},
            name=f"black-penguin-{config.id}-{len(_firebase_apps)}",
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Firebase Admin SDK could not be initialized.") from exc
    _firebase_apps[cache_key] = app
    return app


def get_firebase_app(db: Session):
    return _initialize_app(_configuration(db))


def create_identity(db: Session, *, uid: str, email: str, display_name: str, password: str):
    from firebase_admin import auth
    app = get_firebase_app(db)
    try:
        return auth.create_user(
            uid=uid, email=email, display_name=display_name or None,
            password=password, email_verified=False, disabled=False, app=app,
        )
    except auth.EmailAlreadyExistsError:
        existing = auth.get_user_by_email(email, app=app)
        if existing.uid != uid:
            raise HTTPException(status_code=409, detail="This email already belongs to another Firebase identity.")
        return existing
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Firebase could not provision the user identity.") from exc


def update_identity(
    db: Session, *, uid: str, email: str | None = None,
    display_name: str | None = None, disabled: bool | None = None,
    email_verified: bool | None = None, password: str | None = None,
):
    from firebase_admin import auth
    values = {key: value for key, value in {
        "email": email, "display_name": display_name, "disabled": disabled,
        "email_verified": email_verified, "password": password,
    }.items() if value is not None}
    try:
        return auth.update_user(uid, app=get_firebase_app(db), **values)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Firebase could not update the user identity.") from exc


def delete_identity(db: Session, uid: str) -> None:
    from firebase_admin import auth
    try:
        auth.delete_user(uid, app=get_firebase_app(db))
    except auth.UserNotFoundError:
        return


def _request(config: FirebaseConfig, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{IDENTITY_TOOLKIT}/{endpoint}", params={"key": config.api_key},
            json=payload, timeout=15.0,
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Firebase Authentication is temporarily unavailable.") from exc
    if response.is_error:
        code = str(data.get("error", {}).get("message", "FIREBASE_REQUEST_FAILED")).split(" : ", 1)[0]
        status_code = 401 if code in {"INVALID_PASSWORD", "EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS"} else 422
        raise HTTPException(status_code=status_code, detail=code)
    return data


def send_password_action_email(db: Session, email: str) -> None:
    config = _configuration(db)
    _request(config, "accounts:sendOobCode", {
        "requestType": "PASSWORD_RESET",
        "email": email,
        "continueUrl": config.action_handler_url,
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
    from firebase_admin import auth
    try:
        return auth.verify_id_token(token, app=get_firebase_app(db), check_revoked=True)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or revoked Firebase identity token.") from exc


def verify_configuration(db: Session) -> dict[str, str]:
    from firebase_admin import auth
    config = _configuration(db, require_enabled=False)
    app = _initialize_app(config)
    try:
        auth.list_users(max_results=1, app=app)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Firebase service account verification failed.") from exc
    return _service_account(config)
