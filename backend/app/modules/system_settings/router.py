from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from sqlalchemy import func
from app.modules.companies.models import Company

from .schemas import (
    FirebaseConfigSchema, FirebaseConfigUpdate, GoogleCalendarConfigSchema, GoogleCalendarConfigUpdate,
    MetaPlatformConfigSchema, MetaPlatformConfigUpdate,
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
    return services.firebase_config_response(services.get_firebase_config(db))

@router.put("/email-settings", response_model=FirebaseConfigSchema, summary="Actualizar configuración de Firebase Email")
def update_email_settings(
    payload: FirebaseConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.firebase_config_response(services.update_firebase_config(db, payload))


@router.post("/email-settings/verify", response_model=FirebaseConfigSchema, summary="Verify Firebase Authentication")
def verify_email_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.firebase_config_response(services.verify_firebase_config(db))

# =========================================================
# ⚙️ MESSAGING SETTINGS (TWILIO)
# =========================================================
@router.get("/messaging-settings", response_model=TwilioConfigSchema, summary="Obtener configuración de Twilio SMS")
def get_messaging_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.twilio_config_response(services.get_twilio_config(db))

@router.put("/messaging-settings", response_model=TwilioConfigSchema, summary="Actualizar configuración de Twilio SMS")
def update_messaging_settings(
    payload: TwilioConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.twilio_config_response(services.update_twilio_config(db, payload))


@router.post("/messaging-settings/verify", response_model=TwilioConfigSchema, summary="Verificar configuración de Twilio")
def verify_messaging_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.twilio_config_response(services.verify_twilio_config(db))


@router.get("/integrations/google-calendar", response_model=GoogleCalendarConfigSchema)
def get_google_calendar_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.google_calendar_config_response(services.get_google_calendar_config(db))


@router.put("/integrations/google-calendar", response_model=GoogleCalendarConfigSchema)
def update_google_calendar_settings(
    payload: GoogleCalendarConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.google_calendar_config_response(services.update_google_calendar_config(db, payload))


@router.get("/integrations/meta", response_model=MetaPlatformConfigSchema)
def get_meta_platform_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.meta_platform_config_response(services.get_meta_platform_config(db))


@router.put("/integrations/meta", response_model=MetaPlatformConfigSchema)
def update_meta_platform_settings(
    payload: MetaPlatformConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.meta_platform_config_response(services.update_meta_platform_config(db, payload))


@router.post("/integrations/meta/verify", response_model=MetaPlatformConfigSchema)
def verify_meta_platform_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return services.meta_platform_config_response(services.verify_meta_platform_config(db))


@router.post("/integrations/meta/rotate-webhook-token")
def rotate_meta_webhook_token(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    config, token = services.rotate_meta_webhook_verify_token(db)
    return {"config": services.meta_platform_config_response(config), "verify_token": token}

# =========================================================
# 📄 DOCUMENTOS LEGALES (PRIVACY & TERMS)
# =========================================================
@router.get("/legal/{doc_type}", response_model=LegalDocumentResponse, summary="Obtener un documento legal")
def get_legal_document(
    doc_type: str,
    lang: str = "en",
    db: Session = Depends(get_db)
    # 🚀 AQUÍ ELIMINAMOS EL DEPENDS DEL USUARIO SUPERADMIN
):
    return services.get_legal_document(db, doc_type, lang)


@router.put("/legal/{doc_type}", response_model=LegalDocumentResponse, summary="Actualizar un documento legal")
def update_legal_document(
    doc_type: str,
    payload: LegalDocumentPayload,
    lang: str = "en",
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])) 
    # 🔒 ESTE LO MANTENEMOS: Solo el Superadmin puede guardar/editar el documento
):
    return services.update_legal_document(db, doc_type, payload, lang)

# ==========================================
# DASHBOARD STATS
# ==========================================
@router.get("/stats/")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Devuelve las métricas globales para el Dashboard del Superadmin."""
    
    # 1. Total de Empresas
    total_companies = db.query(func.count(Company.id)).scalar() or 0
    
    # 2. Total de Tokens y Costo (Usando func.sum)
    total_tokens = db.query(func.sum(Company.ai_tokens_used)).scalar() or 0
    total_usd = db.query(func.sum(Company.ai_cost_usd)).scalar() or 0.0
    
    # 3. Últimas 5 empresas
    recent_companies_query = db.query(Company).order_by(Company.created_at.desc()).limit(5).all()
    
    recent_companies = []
    for c in recent_companies_query:
        recent_companies.append({
            "id": c.id,
            "name": c.name,
            "plan_name": c.plan.name if c.plan else "Standard",
            "status": "Active" if c.is_active else "Inactive",
            "created_at": c.created_at
        })
        
    return {
        "total_companies": total_companies,
        "total_tokens": total_tokens,
        "total_usd": total_usd,
        "recent_companies": recent_companies
    }
