from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from .schemas import (
    FirebaseConfigSchema, FirebaseConfigUpdate,
    TwilioConfigSchema, TwilioConfigUpdate,
    LegalDocumentResponse, LegalDocumentPayload
)
from . import services

router = APIRouter()

# =========================================================
# ⚙️ EMAIL SETTINGS (FIREBASE)
# =========================================================
@router.get("/email-settings", response_model=FirebaseConfigSchema, summary="Obtener configuración de Firebase Email")
def get_email_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.get_firebase_config(db)

@router.put("/email-settings", response_model=FirebaseConfigSchema, summary="Actualizar configuración de Firebase Email")
def update_email_settings(
    payload: FirebaseConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.update_firebase_config(db, payload)

# =========================================================
# ⚙️ MESSAGING SETTINGS (TWILIO)
# =========================================================
@router.get("/messaging-settings", response_model=TwilioConfigSchema, summary="Obtener configuración de Twilio SMS")
def get_messaging_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.get_twilio_config(db)

@router.put("/messaging-settings", response_model=TwilioConfigSchema, summary="Actualizar configuración de Twilio SMS")
def update_messaging_settings(
    payload: TwilioConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.update_twilio_config(db, payload)

# =========================================================
# 📄 DOCUMENTOS LEGALES (PRIVACY & TERMS)
# =========================================================
@router.get("/legal/{doc_type}", response_model=LegalDocumentResponse, summary="Obtener documento legal")
def get_legal_document(doc_type: str, lang: str = "en", db: Session = Depends(get_db)):
    """Endpoint público para leer Políticas de Privacidad y Términos."""
    if doc_type not in ["privacy", "terms"]:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")
    return services.get_legal_document(db, doc_type, lang)

@router.put("/legal/{doc_type}", response_model=LegalDocumentResponse, summary="Actualizar documento legal")
def update_legal_document(
    doc_type: str,
    payload: LegalDocumentPayload,
    lang: str = "en",
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.update_legal_document(db, doc_type, payload, lang)