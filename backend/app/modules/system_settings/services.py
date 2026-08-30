from datetime import datetime
import re

import httpx
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import FirebaseConfig, TwilioConfig, LegalDocument
from .schemas import FirebaseConfigUpdate, TwilioConfigUpdate, LegalDocumentPayload
from app.core.config import settings
from app.core.secret_store import decrypt_secret, encrypt_secret

# --- FIREBASE ---
def get_firebase_config(db: Session) -> FirebaseConfig:
    config = db.query(FirebaseConfig).first()
    if not config:
        config = FirebaseConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def update_firebase_config(db: Session, payload: FirebaseConfigUpdate) -> FirebaseConfig:
    config = get_firebase_config(db)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
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
    token = decrypt_secret(config.auth_token_ciphertext)
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
