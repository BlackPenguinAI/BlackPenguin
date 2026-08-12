from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker, get_current_user
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole

from .schemas import AIConfigUpdatePayload, AIConfigResponse
from . import services

router = APIRouter()

@router.get("/config", response_model=AIConfigResponse, summary="Obtener configuración de IA")
def get_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, *TENANT_MANAGER_ROLES]))
):
    return services.get_ai_config(db, company_id=current_user.company_id)

@router.put("/config", summary="Actualizar configuración de IA y prompts")
def update_config(
    payload: AIConfigUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, *TENANT_MANAGER_ROLES]))
):
    services.update_ai_config(db, payload, company_id=current_user.company_id)
    return {"message": "Configuración Multi-Agente actualizada con éxito."}

@router.get("/config/consumption", summary="Consultar saldo de OpenRouter")
def get_api_consumption(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, *TENANT_MANAGER_ROLES]))
):
    return services.get_consumption(db, company_id=current_user.company_id)
