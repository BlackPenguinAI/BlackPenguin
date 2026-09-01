from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException
from .models import AIConfiguration, PromptVersion
from .schemas import AIConfigUpdatePayload
from app.integrations.openrouter_client import check_openrouter_consumption
from app.modules.sales_agent.default_prompt import (
    SALES_AGENT_DEFAULT_CONFIG,
    merge_sales_agent_defaults,
    needs_sales_agent_default,
)


def _apply_safe_defaults(db: Session, config: AIConfiguration) -> AIConfiguration:
    merged = merge_sales_agent_defaults(config.agent_ventas)
    if merged != config.agent_ventas:
        config.agent_ventas = merged
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

def update_ai_config(db: Session, payload: AIConfigUpdatePayload, company_id: str = None, actor_id: str | None = None) -> AIConfiguration:
    config = get_ai_config(db, company_id)
    if company_id is not None and config.company_id is None:
        config = AIConfiguration(
            company_id=company_id,
            openrouter_api_key=config.openrouter_api_key,
            available_models=list(config.available_models or []),
            agent_onboarding_empresa=dict(config.agent_onboarding_empresa or {}),
            agent_onboarding_proyectos=dict(config.agent_onboarding_proyectos or {}),
            agent_ventas=dict(config.agent_ventas or {}),
            agent_reporteria=dict(config.agent_reporteria or {}),
        )
        db.add(config)
        db.flush()
    config = db.query(AIConfiguration).filter(AIConfiguration.id == config.id).with_for_update().one()

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
        validate_sales_configuration(payload.agent_ventas.model_dump())
        config.agent_ventas = payload.agent_ventas.model_dump()
        flag_modified(config, "agent_ventas")
        latest = db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == "sales").order_by(PromptVersion.version_number.desc()).first()
        db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == "sales", PromptVersion.is_published.is_(True)).update({PromptVersion.is_published: False}, synchronize_session=False)
        db.add(PromptVersion(company_id=company_id, agent_key="sales", version_number=(latest.version_number + 1 if latest else 1), configuration=payload.agent_ventas.model_dump(), is_published=True, created_by_user_id=actor_id))

    if payload.agent_reporteria is not None:
        config.agent_reporteria = payload.agent_reporteria.model_dump()
        flag_modified(config, "agent_reporteria")

    db.commit()
    db.refresh(config)
    return config


def prompt_versions(
    db: Session, *, company_id: str | None, agent_key: str,
    offset: int = 0, limit: int = 20,
) -> tuple[list[PromptVersion], int]:
    query = db.query(PromptVersion).filter(
        PromptVersion.company_id == company_id,
        PromptVersion.agent_key == agent_key,
    )
    total = query.count()
    items = query.order_by(PromptVersion.version_number.desc()).offset(offset).limit(limit).all()
    return items, total


def prompt_version(
    db: Session, *, company_id: str | None, agent_key: str, version_id: str,
) -> PromptVersion:
    item = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.company_id == company_id,
        PromptVersion.agent_key == agent_key,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Prompt version not found.")
    return item


def create_prompt_draft(db: Session, *, company_id: str | None, agent_key: str, configuration: dict, change_note: str, actor_id: str) -> PromptVersion:
    validate_sales_configuration(configuration)
    config = get_ai_config(db, company_id)
    db.query(AIConfiguration).filter(AIConfiguration.id == config.id).with_for_update().one()
    latest = db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key).order_by(PromptVersion.version_number.desc()).first()
    item = PromptVersion(company_id=company_id, agent_key=agent_key, version_number=(latest.version_number + 1 if latest else 1), configuration=configuration, is_published=False, published_at=None, change_note=change_note[:500], created_by_user_id=actor_id)
    db.add(item); db.commit(); db.refresh(item); return item


def validate_sales_configuration(configuration: dict) -> None:
    scoring = configuration.get("scoring_config") or {}
    hot = int(scoring.get("hot_threshold", 70)); warm = int(scoring.get("warm_threshold", 40))
    if not 0 <= warm < hot <= 100:
        raise HTTPException(status_code=422, detail="Scoring thresholds must satisfy 0 ≤ warm < hot ≤ 100.")
    for key in ("timeline", "financial_readiness", "budget_fit", "engagement", "decision_authority", "specificity"):
        value = int(scoring.get(key, SALES_AGENT_DEFAULT_CONFIG["scoring_config"][key]))
        if value < 0 or value > 100:
            raise HTTPException(status_code=422, detail=f"Scoring weight {key} must be between 0 and 100.")
    cadence = configuration.get("cadence_config") or {}
    for key in ("hot_hours", "warm_hours", "cold_hours"):
        value = int(cadence.get(key, SALES_AGENT_DEFAULT_CONFIG["cadence_config"][key]))
        if value < 1 or value > 2160:
            raise HTTPException(status_code=422, detail=f"Cadence {key} must be between 1 and 2160 hours.")


def publish_prompt_version(db: Session, *, company_id: str | None, agent_key: str, version_id: str, actor_id: str) -> AIConfiguration:
    version = db.query(PromptVersion).filter(PromptVersion.id == version_id, PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key).first()
    if not version: raise HTTPException(status_code=404, detail="Prompt version not found.")
    config = get_ai_config(db, company_id)
    config = db.query(AIConfiguration).filter(AIConfiguration.id == config.id).with_for_update().one()
    db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key, PromptVersion.is_published.is_(True)).update({PromptVersion.is_published: False}, synchronize_session=False)
    config.agent_ventas = merge_sales_agent_defaults(version.configuration); flag_modified(config, "agent_ventas")
    version.is_published = True; version.published_at = datetime.utcnow(); version.created_by_user_id = actor_id
    db.commit(); db.refresh(config); return config


def restore_prompt_version(db: Session, *, company_id: str | None, agent_key: str, version_id: str, actor_id: str) -> AIConfiguration:
    version = db.query(PromptVersion).filter(PromptVersion.id == version_id, PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key).first()
    if not version: raise HTTPException(status_code=404, detail="Prompt version not found.")
    config = get_ai_config(db, company_id)
    if company_id is not None and config.company_id is None:
        config = AIConfiguration(
            company_id=company_id,
            openrouter_api_key=config.openrouter_api_key,
            available_models=list(config.available_models or []),
            agent_onboarding_empresa=dict(config.agent_onboarding_empresa or {}),
            agent_onboarding_proyectos=dict(config.agent_onboarding_proyectos or {}),
            agent_ventas=dict(config.agent_ventas or {}),
            agent_reporteria=dict(config.agent_reporteria or {}),
        )
        db.add(config); db.flush()
    config = db.query(AIConfiguration).filter(AIConfiguration.id == config.id).with_for_update().one()
    if agent_key != "sales": raise HTTPException(status_code=422, detail="Only the Sales Agent registry is available in this release.")
    config.agent_ventas = dict(version.configuration); flag_modified(config, "agent_ventas")
    latest = db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key).order_by(PromptVersion.version_number.desc()).first()
    db.query(PromptVersion).filter(PromptVersion.company_id == company_id, PromptVersion.agent_key == agent_key, PromptVersion.is_published.is_(True)).update({PromptVersion.is_published: False}, synchronize_session=False)
    db.add(PromptVersion(company_id=company_id, agent_key=agent_key, version_number=(latest.version_number + 1 if latest else 1), configuration=dict(version.configuration), is_published=True, created_by_user_id=actor_id))
    db.commit(); db.refresh(config); return config

def get_consumption(db: Session, company_id: str = None) -> dict:
    config = get_ai_config(db, company_id)
    if not config or not config.openrouter_api_key:
        return {"usage": 0, "limit": 0, "error": "No API Key configurada"}
    
    return check_openrouter_consumption(config.openrouter_api_key)
