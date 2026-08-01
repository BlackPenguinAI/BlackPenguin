from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified  # 🚀 IMPORTACIÓN CLAVE: Obliga a PostgreSQL a detectar cambios en JSON
import urllib.request
import json
from typing import List, Dict, Optional

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.auth.models import User, UserRole
from app.modules.ai.models import AIConfiguration

# 🚀 IMPORTAMOS LOS ESQUEMAS BLINDADOS
from app.modules.ai.schemas import (
    AgentConfigSchema,
    AIConfigUpdatePayload,
    AIConfigResponse
)

router = APIRouter()

# =========================================================
# RUTAS DE CONFIGURACIÓN DE IA (Staff / Admin)
# =========================================================

@router.get("/config", response_model=AIConfigResponse, summary="Obtener configuración de IA")
def get_ai_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    """Consulta la configuración del motor de IA para la empresa o a nivel global."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
    
    # Fallback: Si no tiene configuración asignada, busca la global
    if not config:
        config = db.query(AIConfiguration).filter(AIConfiguration.company_id == None).first()
        
    # Si no existe ninguna configuración en la DB, crea la primera
    if not config:
        config = AIConfiguration(company_id=current_user.company_id)
        db.add(config)
        db.commit()
        db.refresh(config)
        
    return config


@router.put("/config", summary="Actualizar configuración de IA y prompts")
def update_ai_config(
    payload: AIConfigUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    """Actualiza la configuración del motor de IA y los prompts de los agentes."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
    
    if not config:
        config = db.query(AIConfiguration).filter(AIConfiguration.company_id == None).first()
        
    if not config:
        config = AIConfiguration(company_id=current_user.company_id)
        db.add(config)
        db.commit()

    # 1. Actualización de API Key y Modelos Disponibles
    if payload.openrouter_api_key is not None:
        config.openrouter_api_key = payload.openrouter_api_key
        
    if payload.available_models is not None:
        config.available_models = payload.available_models
        flag_modified(config, "available_models")

    # 2. Actualización de Agentes (JSON)
    if payload.agent_onboarding_empresa is not None:
        config.agent_onboarding_empresa = payload.agent_onboarding_empresa.model_dump()
        flag_modified(config, "agent_onboarding_empresa")

    if payload.agent_onboarding_proyectos is not None:
        config.agent_onboarding_proyectos = payload.agent_onboarding_proyectos.model_dump()
        flag_modified(config, "agent_onboarding_proyectos")

    if payload.agent_ventas is not None:
        config.agent_ventas = payload.agent_ventas.model_dump()
        flag_modified(config, "agent_ventas")

    if payload.agent_reporteria is not None:
        config.agent_reporteria = payload.agent_reporteria.model_dump()
        flag_modified(config, "agent_reporteria")

    db.commit()
    db.refresh(config)
    return {"message": "Configuración Multi-Agente actualizada con éxito."}


@router.get("/config/consumption", summary="Consultar saldo de OpenRouter")
def get_api_consumption(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))
):
    """Consulta la API de OpenRouter en tiempo real para ver el saldo y límite de la llave configurada."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
    if not config or not config.openrouter_api_key:
        config = db.query(AIConfiguration).filter(AIConfiguration.company_id == None).first()
        
    if not config or not config.openrouter_api_key:
        return {"usage": 0, "limit": 0, "error": "No API Key"}
        
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key", 
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"}
        )
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            key_data = data.get("data", {})
            return {
                "usage": key_data.get("usage", 0),
                "limit": key_data.get("limit", 0),
                "label": key_data.get("label", "OpenRouter Key")
            }
    except Exception as e:
        return {"usage": 0, "limit": 0, "error": str(e)}