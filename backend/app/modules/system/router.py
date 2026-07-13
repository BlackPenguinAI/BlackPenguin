from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.postgres import get_db
from datetime import datetime # 🚀 Importación vital para la fecha

from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

from app.modules.system.models import SmtpConfig, LegalDocument
from app.modules.system.schemas import (
    SmtpConfigSchema,
    LegalDocumentPayload,
    LegalDocumentResponse
)

router = APIRouter()

# =========================================================
# 📧 ENDPOINTS DE CONFIGURACIÓN SMTP
# =========================================================

@router.get("/smtp-config", response_model=SmtpConfigSchema, summary="Obtener config SMTP")
def get_smtp_config(
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    config = db.query(SmtpConfig).first()
    if not config:
        return SmtpConfigSchema(
            smtp_host="", smtp_port=587, smtp_user="", 
            smtp_password="", smtp_security="TLS", sender_email="no-reply@blackpenguin.ai"
        )
    return config

@router.put("/smtp-config", summary="Actualizar config SMTP")
def update_smtp_config(
    payload: SmtpConfigSchema, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    config = db.query(SmtpConfig).first()
    if not config:
        config = SmtpConfig(**payload.model_dump())
        db.add(config)
    else:
        for key, value in payload.model_dump().items():
            setattr(config, key, value)
    db.commit()
    return {"message": "Configuración SMTP actualizada exitosamente."}

# =========================================================
# 📄 ENDPOINTS DE DOCUMENTOS LEGALES (MARKDOWN)
# =========================================================

@router.get("/legal/{doc_type}", response_model=LegalDocumentResponse, summary="Obtener texto legal")
def get_legal_document(doc_type: str, lang: str = "en", db: Session = Depends(get_db)):
    if doc_type not in ["privacy", "terms"]:
        raise HTTPException(status_code=400, detail="Documento inválido.")
        
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type, 
        LegalDocument.language == lang
    ).first()
    
    if not document:
        # Estructura por defecto alineada al nuevo esquema
        return {
            "doc_type": doc_type,
            "language": lang,
            "last_updated_label": "July 2026" if lang == "en" else "Julio 2026",
            "content_markdown": f"# {doc_type.capitalize()} Policy\n\n*Content under construction.*",
            "updated_at": datetime.utcnow()
        }
        
    return document

@router.put("/legal/{doc_type}", summary="Actualizar texto legal")
def update_legal_document(
    doc_type: str, 
    payload: LegalDocumentPayload, 
    lang: str = "en", 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    if doc_type not in ["privacy", "terms"]:
        raise HTTPException(status_code=400, detail="Documento inválido.")
        
    document = db.query(LegalDocument).filter(
        LegalDocument.doc_type == doc_type, 
        LegalDocument.language == lang
    ).first()
    
    if not document:
        document = LegalDocument(
            doc_type=doc_type, 
            language=lang, 
            content_markdown=payload.content_markdown,
            last_updated_label=payload.last_updated_label # 🚀 Guarda la fecha dedicada
        )
        db.add(document)
    else:
        document.content_markdown = payload.content_markdown
        document.last_updated_label = payload.last_updated_label # 🚀 Actualiza la fecha dedicada
        
    db.commit()
    return {"message": "Documento legal actualizado exitosamente en vivo."}