from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker, get_current_user
from app.modules.users.models import User, UserRole

from .schemas import AIConfigUpdatePayload, AIConfigResponse, SalesPromptDraftPayload
from . import services

router = APIRouter()

@router.get("/config", response_model=AIConfigResponse, summary="Obtener configuración de IA")
def get_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.get_ai_config(db, company_id=current_user.company_id)

@router.put("/config", summary="Actualizar configuración de IA y prompts")
def update_config(
    payload: AIConfigUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    services.update_ai_config(db, payload, company_id=current_user.company_id, actor_id=current_user.id)
    return {"message": "Configuración Multi-Agente actualizada con éxito."}


@router.get("/prompts/sales/versions")
def list_sales_prompt_versions(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    return [{"id": item.id, "version": item.version_number, "is_published": item.is_published, "created_at": item.created_at, "published_at": item.published_at, "created_by_user_id": item.created_by_user_id, "change_note": item.change_note, "configuration": item.configuration} for item in services.prompt_versions(db, company_id=current_user.company_id, agent_key="sales")]


@router.post("/prompts/sales/drafts")
def create_sales_prompt_draft(
    payload: SalesPromptDraftPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    item = services.create_prompt_draft(db, company_id=None, agent_key="sales", configuration=payload.configuration.model_dump(), change_note=payload.change_note, actor_id=current_user.id)
    return {"id": item.id, "version": item.version_number, "is_published": item.is_published, "change_note": item.change_note, "created_at": item.created_at}


@router.post("/prompts/sales/versions/{version_id}/publish")
def publish_sales_prompt_version(
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    services.publish_prompt_version(db, company_id=None, agent_key="sales", version_id=version_id, actor_id=current_user.id)
    return {"message": "Sales Agent prompt version published."}


@router.post("/prompts/sales/versions/{version_id}/restore")
def restore_sales_prompt_version(
    version_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN])),
):
    services.restore_prompt_version(db, company_id=current_user.company_id, agent_key="sales", version_id=version_id, actor_id=current_user.id)
    return {"message": "Sales Agent prompt version restored as a new published version."}

@router.get("/config/consumption", summary="Consultar saldo de OpenRouter")
def get_api_consumption(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return services.get_consumption(db, company_id=current_user.company_id)
