from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.postgres import get_db

from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

from app.modules.system.models import SmtpConfig
from app.modules.system.schemas import SmtpConfigSchema

router = APIRouter()

@router.get("/smtp-config", response_model=SmtpConfigSchema, summary="Obtener config SMTP")
def get_smtp_config(
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Devuelve la configuración actual. Si no existe, devuelve valores vacíos."""
    config = db.query(SmtpConfig).first()
    
    if not config:
        # Valores por defecto para que Angular no de error
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
    """Crea o actualiza la configuración global de correos."""
    config = db.query(SmtpConfig).first()
    
    if not config:
        # Si no existe, la creamos
        new_config = SmtpConfig(**payload.model_dump())
        db.add(new_config)
    else:
        # Si ya existe, la actualizamos
        update_data = payload.model_dump()
        for key, value in update_data.items():
            setattr(config, key, value)
            
    db.commit()
    return {"message": "Configuración SMTP actualizada con éxito."}