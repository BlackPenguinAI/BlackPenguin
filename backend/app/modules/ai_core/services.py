from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException
from .models import AIConfiguration
from .schemas import AIConfigUpdatePayload
from app.integrations.openrouter_client import check_openrouter_consumption
from app.modules.sales_agent.default_prompt import (
    SALES_AGENT_DEFAULT_CONFIG,
    needs_sales_agent_default,
)


def _apply_safe_defaults(db: Session, config: AIConfiguration) -> AIConfiguration:
    if needs_sales_agent_default(config.agent_ventas):
        config.agent_ventas = dict(SALES_AGENT_DEFAULT_CONFIG)
        flag_modified(config, "agent_ventas")
        db.commit()
        db.refresh(config)
    return config

def get_ai_config(db: Session, company_id: str = None) -> AIConfiguration:
    # 1. Buscar configuración específica de la empresa
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == company_id).first()
    
    # 2. Fallback: Buscar configuración global (company_id = None)
    if not config and company_id is not None:
        config = db.query(AIConfiguration).filter(AIConfiguration.company_id == None).first()
        
    # 3. Si no existe ninguna, la inicializamos vacía
    if not config:
        config = AIConfiguration(company_id=company_id)
        db.add(config)
        db.commit()
        db.refresh(config)
        
    return _apply_safe_defaults(db, config)

def update_ai_config(db: Session, payload: AIConfigUpdatePayload, company_id: str = None) -> AIConfiguration:
    config = get_ai_config(db, company_id)

    if payload.openrouter_api_key is not None:
        config.openrouter_api_key = payload.openrouter_api_key
        
    if payload.available_models is not None:
        config.available_models = payload.available_models
        flag_modified(config, "available_models")

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
    return config

def get_consumption(db: Session, company_id: str = None) -> dict:
    config = get_ai_config(db, company_id)
    if not config or not config.openrouter_api_key:
        return {"usage": 0, "limit": 0, "error": "No API Key configurada"}
    
    return check_openrouter_consumption(config.openrouter_api_key)
