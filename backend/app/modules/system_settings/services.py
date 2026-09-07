from datetime import datetime
import re
import secrets

import httpx
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import FirebaseConfig, GoogleCalendarConfig, MetaPlatformConfig, TwilioConfig, LegalDocument
from .schemas import (
    FirebaseConfigUpdate, GoogleCalendarConfigUpdate, LegalDocumentPayload,
    MetaPlatformConfigUpdate, TwilioConfigUpdate,
)
from app.core.config import settings
from app.core.secret_store import decrypt_secret, encrypt_secret


META_OAUTH_SCOPES = [
    "business_management", "pages_show_list", "pages_read_engagement",
    "pages_manage_metadata", "leads_retrieval", "ads_read",
]

# --- FIREBASE ---
def get_firebase_config(db: Session) -> FirebaseConfig:
    config = db.query(FirebaseConfig).first()
    if not config:
        config = FirebaseConfig(
            api_key=settings.FIREBASE_API_KEY or None,
            auth_domain=settings.FIREBASE_AUTH_DOMAIN or None,
            project_id=settings.FIREBASE_PROJECT_ID or None,
            is_enabled=False,
            auth_mode="rest",
            action_handler_url=f"{settings.PUBLIC_APP_URL.rstrip('/')}/activate-account",
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    if config.auth_mode != "rest":
        config.auth_mode = "rest"
        db.commit(); db.refresh(config)
    return config


def firebase_config_response(config: FirebaseConfig) -> dict:
    return {
        "id": config.id, "api_key": config.api_key, "auth_domain": config.auth_domain,
        "project_id": config.project_id,
        "is_enabled": bool(config.is_enabled), "auth_mode": "rest",
        "action_handler_url": config.action_handler_url,
        "verification_status": config.verification_status or "not_configured",
        "verified_at": config.verified_at, "last_error": config.last_error,
        "updated_at": config.updated_at,
    }

def update_firebase_config(db: Session, payload: FirebaseConfigUpdate) -> FirebaseConfig:
    config = get_firebase_config(db)
    update_data = payload.model_dump(exclude_unset=True)
    update_data["auth_mode"] = "rest"
    connection_changed = any(
        key in update_data and update_data[key] != getattr(config, key)
        for key in ("api_key", "auth_domain", "project_id", "action_handler_url")
    )
    for key, value in update_data.items():
        setattr(config, key, value)
    if config.action_handler_url and not config.action_handler_url.startswith("https://"):
        raise HTTPException(status_code=422, detail="Firebase Action Handler URL must use HTTPS.")
    if config.is_enabled and not (config.api_key and config.project_id and config.action_handler_url):
        raise HTTPException(status_code=422, detail="Complete Firebase Project ID, Web API Key and Action Handler URL before enabling Authentication.")
    if config.is_enabled and config.verification_status != "verified":
        raise HTTPException(status_code=422, detail="Test Firebase successfully before enabling Authentication.")
    if connection_changed:
        config.is_enabled = False
        config.verification_status = "pending"
        config.verified_at = None
        config.last_error = None
    db.commit()
    db.refresh(config)
    return config


def verify_firebase_config(db: Session) -> FirebaseConfig:
    config = get_firebase_config(db)
    try:
        from app.integrations.firebase_client import verify_configuration
        verify_configuration(db)
    except HTTPException as exc:
        config.is_enabled = False
        config.verification_status = "failed"
        config.last_error = str(exc.detail)
        db.commit()
        raise
    config.verification_status = "verified"
    config.verified_at = datetime.utcnow()
    config.last_error = None
    db.commit(); db.refresh(config)
    return config

# --- TWILIO ---
def get_twilio_config(db: Session) -> TwilioConfig:
    config = db.query(TwilioConfig).first()
    if not config:
        config = TwilioConfig(
            account_sid=settings.TWILIO_ACCOUNT_SID or None,
            from_phone_number=settings.TWILIO_FROM_PHONE_NUMBER or None,
            auth_token_ciphertext=encrypt_secret(settings.TWILIO_AUTH_TOKEN),
            auth_token_hint=settings.TWILIO_AUTH_TOKEN[-4:] if settings.TWILIO_AUTH_TOKEN else None,
            live_sms_enabled=False,
            verification_status="pending" if settings.TWILIO_AUTH_TOKEN else "not_configured",
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    if config.auth_token and not config.auth_token_ciphertext:
        config.auth_token_ciphertext = encrypt_secret(config.auth_token)
        config.auth_token_hint = config.auth_token[-4:]
        config.auth_token = None
        db.commit(); db.refresh(config)
    defaults_changed = False
    if not config.account_sid and settings.TWILIO_ACCOUNT_SID:
        config.account_sid = settings.TWILIO_ACCOUNT_SID
        defaults_changed = True
    if not config.from_phone_number and settings.TWILIO_FROM_PHONE_NUMBER:
        config.from_phone_number = settings.TWILIO_FROM_PHONE_NUMBER
        defaults_changed = True
    if defaults_changed:
        db.commit(); db.refresh(config)
    return config


def twilio_config_response(config: TwilioConfig) -> dict:
    return {
        "id": config.id,
        "account_sid": config.account_sid,
        "auth_token_configured": bool(config.auth_token_ciphertext),
        "auth_token_hint": config.auth_token_hint,
        "from_phone_number": config.from_phone_number,
        "live_sms_enabled": bool(config.live_sms_enabled),
        "verification_status": config.verification_status or "not_configured",
        "verified_at": config.verified_at,
        "last_error": config.last_error,
        "updated_at": config.updated_at,
    }


def twilio_credentials(db: Session) -> tuple[TwilioConfig, str]:
    config = get_twilio_config(db)
    try:
        token = decrypt_secret(config.auth_token_ciphertext)
    except ValueError as exc:
        config.verification_status = "failed"; config.last_error = "credential_decryption_failed"
        db.commit()
        raise HTTPException(status_code=409, detail="The stored Twilio token cannot be decrypted. Replace and save the Auth Token.") from exc
    if not config.account_sid or not token or not config.from_phone_number:
        raise HTTPException(status_code=409, detail="Twilio is not fully configured.")
    return config, token


def _normalize_e164(value: str | None) -> str | None:
    if not value:
        return None
    compact = "+" + re.sub(r"\D", "", value)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", compact):
        raise HTTPException(status_code=422, detail="From Phone Number must use E.164 format.")
    return compact

def update_twilio_config(db: Session, payload: TwilioConfigUpdate) -> TwilioConfig:
    config = get_twilio_config(db)
    update_data = payload.model_dump(exclude_unset=True)
    token = update_data.pop("auth_token", None)
    if "from_phone_number" in update_data:
        update_data["from_phone_number"] = _normalize_e164(update_data["from_phone_number"])
    credentials_changed = bool(token) or any(
        key in update_data and update_data[key] != getattr(config, key)
        for key in ("account_sid", "from_phone_number")
    )
    if token:
        config.auth_token_ciphertext = encrypt_secret(token)
        config.auth_token_hint = token[-4:]
    for key, value in update_data.items(): setattr(config, key, value)
    if config.account_sid and not re.fullmatch(r"AC[a-fA-F0-9]{32}", config.account_sid):
        raise HTTPException(status_code=422, detail="Twilio Account SID must use the ACxxxxxxxx format.")
    if config.live_sms_enabled and not (config.account_sid and config.auth_token_ciphertext and config.from_phone_number):
        raise HTTPException(status_code=422, detail="Verify complete Twilio credentials before enabling live SMS.")
    if config.live_sms_enabled and config.verification_status != "verified" and not credentials_changed:
        raise HTTPException(status_code=422, detail="Verify Twilio before enabling live SMS.")
    if credentials_changed:
        config.live_sms_enabled = False
        config.verification_status = "pending"
        config.verified_at = None
        config.last_error = None
    db.commit()
    db.refresh(config)
    return config


def verify_twilio_config(db: Session) -> TwilioConfig:
    config, token = twilio_credentials(db)
    try:
        response = httpx.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.account_sid}.json",
            auth=(config.account_sid, token), timeout=15.0,
        )
        response.raise_for_status()
        number_response = httpx.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{config.account_sid}/IncomingPhoneNumbers.json",
            params={"PhoneNumber": config.from_phone_number, "PageSize": 1},
            auth=(config.account_sid, token), timeout=15.0,
        )
        number_response.raise_for_status()
        if not number_response.json().get("incoming_phone_numbers"):
            raise HTTPException(status_code=422, detail="The SMS From number does not belong to this Twilio account.")
    except HTTPException:
        config.verification_status = "failed"
        config.last_error = "from_number_not_found"
        db.commit()
        raise


    except httpx.HTTPError as exc:
        config.verification_status = "failed"
        config.last_error = type(exc).__name__
        db.commit()
        raise HTTPException(status_code=422, detail="Twilio credentials could not be verified.") from exc
    config.verification_status = "verified"
    config.verified_at = datetime.utcnow()
    config.last_error = None
    db.commit(); db.refresh(config)
    return config


# --- GOOGLE CALENDAR PLATFORM OAUTH ---
def get_google_calendar_config(db: Session) -> GoogleCalendarConfig:
    config = db.query(GoogleCalendarConfig).first()
    if not config:
        config = GoogleCalendarConfig(
            client_id=settings.GOOGLE_CALENDAR_CLIENT_ID or None,
            client_secret_ciphertext=encrypt_secret(settings.GOOGLE_CALENDAR_CLIENT_SECRET),
            client_secret_hint=settings.GOOGLE_CALENDAR_CLIENT_SECRET[-4:] if settings.GOOGLE_CALENDAR_CLIENT_SECRET else None,
            redirect_uri=settings.GOOGLE_CALENDAR_REDIRECT_URI,
            is_enabled=bool(settings.GOOGLE_CALENDAR_CLIENT_ID and settings.GOOGLE_CALENDAR_CLIENT_SECRET),
            verification_status="ready" if settings.GOOGLE_CALENDAR_CLIENT_ID and settings.GOOGLE_CALENDAR_CLIENT_SECRET else "not_configured",
        )
        db.add(config); db.commit(); db.refresh(config)
    bootstrapped = False
    if not config.client_id and settings.GOOGLE_CALENDAR_CLIENT_ID:
        config.client_id = settings.GOOGLE_CALENDAR_CLIENT_ID; bootstrapped = True
    if not config.client_secret_ciphertext and settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        config.client_secret_ciphertext = encrypt_secret(settings.GOOGLE_CALENDAR_CLIENT_SECRET)
        config.client_secret_hint = settings.GOOGLE_CALENDAR_CLIENT_SECRET[-4:]; bootstrapped = True
    if bootstrapped and config.client_id and config.client_secret_ciphertext:
        config.is_enabled = True; config.verification_status = "ready"
        db.commit(); db.refresh(config)
    return config


def google_calendar_config_response(config: GoogleCalendarConfig) -> dict:
    return {
        "id": config.id,
        "client_id": config.client_id,
        "client_secret_configured": bool(config.client_secret_ciphertext),
        "client_secret_hint": config.client_secret_hint,
        "redirect_uri": config.redirect_uri,
        "is_enabled": bool(config.is_enabled),
        "verification_status": config.verification_status,
        "last_error": config.last_error,
        "updated_at": config.updated_at,
    }


def update_google_calendar_config(db: Session, payload: GoogleCalendarConfigUpdate) -> GoogleCalendarConfig:
    config = get_google_calendar_config(db)
    values = payload.model_dump(exclude_unset=True)
    secret = values.pop("client_secret", None)
    if secret:
        config.client_secret_ciphertext = encrypt_secret(secret)
        config.client_secret_hint = secret[-4:]
    for key, value in values.items():
        setattr(config, key, value)
    if not config.redirect_uri.startswith("https://"):
        raise HTTPException(status_code=422, detail="Google Calendar redirect URI must use HTTPS.")
    ready = bool(config.client_id and config.client_secret_ciphertext and config.redirect_uri)
    if config.is_enabled and not ready:
        raise HTTPException(status_code=422, detail="Complete Google Calendar OAuth credentials before enabling the integration.")
    config.verification_status = "ready" if ready else "not_configured"
    config.last_error = None
    db.commit(); db.refresh(config)
    return config


def google_calendar_credentials(db: Session) -> tuple[GoogleCalendarConfig, str]:
    config = get_google_calendar_config(db)
    if not config.is_enabled or config.verification_status != "ready":
        raise HTTPException(status_code=409, detail="Google Calendar OAuth is not configured by Black Penguin.")
    try:
        secret = decrypt_secret(config.client_secret_ciphertext)
    except ValueError as exc:
        config.verification_status = "failed"; config.last_error = "credential_decryption_failed"
        db.commit()
        raise HTTPException(status_code=409, detail="The stored Google Client Secret cannot be decrypted. Replace and save it from Integrations.") from exc
    if not config.client_id or not secret:
        raise HTTPException(status_code=409, detail="Google Calendar OAuth is not configured by Black Penguin.")
    return config, secret


# --- META LEAD ADS PLATFORM OAUTH ---
def get_meta_platform_config(db: Session) -> MetaPlatformConfig:
    config = db.query(MetaPlatformConfig).first()
    if not config:
        verify_token = settings.META_VERIFY_TOKEN or secrets.token_urlsafe(32)
        config = MetaPlatformConfig(
            app_id=settings.META_APP_ID or None,
            app_secret_ciphertext=encrypt_secret(settings.META_APP_SECRET) if settings.META_APP_SECRET and settings.META_APP_SECRET != "app_secret_de_meta_pendiente" else None,
            app_secret_hint=settings.META_APP_SECRET[-4:] if settings.META_APP_SECRET and settings.META_APP_SECRET != "app_secret_de_meta_pendiente" else None,
            login_config_id=settings.META_LOGIN_CONFIG_ID or None,
            graph_api_version=settings.META_API_VERSION,
            redirect_uri=settings.META_OAUTH_REDIRECT_URI,
            webhook_callback_url=f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/webhooks/meta",
            webhook_verify_token_ciphertext=encrypt_secret(verify_token),
            webhook_verify_token_hint=verify_token[-4:],
            requested_scopes=META_OAUTH_SCOPES,
            verification_status="pending" if settings.META_APP_ID else "not_configured",
        )
        db.add(config); db.commit(); db.refresh(config)
    return config


def meta_platform_config_response(config: MetaPlatformConfig) -> dict:
    return {
        "id": config.id, "app_id": config.app_id,
        "app_secret_configured": bool(config.app_secret_ciphertext),
        "app_secret_hint": config.app_secret_hint,
        "login_config_id": config.login_config_id,
        "graph_api_version": config.graph_api_version,
        "redirect_uri": config.redirect_uri,
        "webhook_callback_url": config.webhook_callback_url,
        "webhook_verify_token_configured": bool(config.webhook_verify_token_ciphertext),
        "webhook_verify_token_hint": config.webhook_verify_token_hint,
        "requested_scopes": list(config.requested_scopes or META_OAUTH_SCOPES),
        "is_enabled": bool(config.is_enabled),
        "verification_status": config.verification_status,
        "app_review_status": config.app_review_status,
        "business_verification_status": config.business_verification_status,
        "verified_at": config.verified_at, "last_error": config.last_error,
        "updated_at": config.updated_at,
    }


def update_meta_platform_config(db: Session, payload: MetaPlatformConfigUpdate) -> MetaPlatformConfig:
    config = get_meta_platform_config(db)
    values = payload.model_dump(exclude_unset=True)
    secret = (values.pop("app_secret", None) or "").strip()
    if secret:
        config.app_secret_ciphertext = encrypt_secret(secret)
        config.app_secret_hint = secret[-4:]
    changed = bool(secret)
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        if key in {"app_id", "login_config_id", "graph_api_version", "redirect_uri", "webhook_callback_url"} and value != getattr(config, key):
            changed = True
        setattr(config, key, value)
    if not re.fullmatch(r"v\d+\.\d+", config.graph_api_version or ""):
        raise HTTPException(status_code=422, detail="Meta Graph API Version must use the vNN.N format.")
    if not (config.redirect_uri or "").startswith("https://") or not (config.webhook_callback_url or "").startswith("https://"):
        raise HTTPException(status_code=422, detail="Meta OAuth and Webhook URLs must use HTTPS.")
    ready = bool(config.app_id and config.app_secret_ciphertext and config.login_config_id and config.redirect_uri)
    if config.is_enabled and (not ready or config.verification_status != "verified"):
        raise HTTPException(status_code=422, detail="Save and verify the complete Meta OAuth configuration before enabling it.")
    if changed:
        config.is_enabled = False
        config.verification_status = "pending" if ready else "not_configured"
        config.verified_at = None
        config.last_error = None
    config.requested_scopes = META_OAUTH_SCOPES
    db.commit(); db.refresh(config)
    return config


def meta_platform_credentials(db: Session, *, require_enabled: bool = True) -> tuple[MetaPlatformConfig, str]:
    config = get_meta_platform_config(db)
    if require_enabled and (not config.is_enabled or config.verification_status != "verified"):
        raise HTTPException(status_code=409, detail="Meta OAuth is not enabled by Black Penguin.")
    try:
        secret = decrypt_secret(config.app_secret_ciphertext)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="The stored Meta App Secret cannot be decrypted. Replace it from Integrations.") from exc
    if not config.app_id or not secret or not config.login_config_id:
        raise HTTPException(status_code=409, detail="Meta OAuth is not fully configured.")
    return config, secret


def verify_meta_platform_config(db: Session) -> MetaPlatformConfig:
    config, secret = meta_platform_credentials(db, require_enabled=False)
    try:
        response = httpx.get(
            f"https://graph.facebook.com/{config.graph_api_version}/{config.app_id}",
            params={"fields": "id,name", "access_token": f"{config.app_id}|{secret}"},
            timeout=20.0,
        )
        response.raise_for_status()
        if str(response.json().get("id") or "") != config.app_id:
            raise HTTPException(status_code=422, detail="Meta returned a different App ID.")
    except HTTPException:
        config.verification_status = "failed"; config.last_error = "app_identity_mismatch"; db.commit()
        raise
    except (httpx.HTTPError, ValueError) as exc:
        config.verification_status = "failed"
        config.last_error = type(exc).__name__
        db.commit()
        raise HTTPException(status_code=422, detail="Meta App credentials could not be verified.") from exc
    config.verification_status = "verified"
    config.verified_at = datetime.utcnow()
    config.last_error = None
    db.commit(); db.refresh(config)
    return config


def rotate_meta_webhook_verify_token(db: Session) -> tuple[MetaPlatformConfig, str]:
    config = get_meta_platform_config(db)
    token = secrets.token_urlsafe(32)
    config.webhook_verify_token_ciphertext = encrypt_secret(token)
    config.webhook_verify_token_hint = token[-4:]
    db.commit(); db.refresh(config)
    return config, token


def meta_webhook_verify_token(db: Session) -> str:
    config = get_meta_platform_config(db)
    try:
        return decrypt_secret(config.webhook_verify_token_ciphertext) or ""
    except ValueError:
        return settings.META_VERIFY_TOKEN

# --- LEGAL ---
def get_legal_document(db: Session, doc_type: str, lang: str = "en") -> LegalDocument:
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type,
        LegalDocument.language == lang
    ).first()
    
    if not document:
        document = LegalDocument(
            doc_type=doc_type,
            language=lang,
            last_updated_label="July 2026" if lang == "en" else "Julio 2026",
            content_markdown=f"# {doc_type.capitalize()} Policy\n\n*Content under construction.*"
        )
        db.add(document)
        db.commit()
        db.refresh(document)
    return document

def update_legal_document(db: Session, doc_type: str, payload: LegalDocumentPayload, lang: str = "en") -> LegalDocument:
    if doc_type not in ["privacy", "terms"]:
        raise HTTPException(status_code=400, detail="Documento legal inválido.")
        
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type,
        LegalDocument.language == lang
    ).first()
    
    if not document:
        document = LegalDocument(
            doc_type=doc_type,
            language=lang,
            content_markdown=payload.content_markdown,
            last_updated_label=payload.last_updated_label
        )
        db.add(document)
    else:
        document.content_markdown = payload.content_markdown
        document.last_updated_label = payload.last_updated_label
        
    db.commit()
    db.refresh(document)
    return document
