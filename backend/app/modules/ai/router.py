from fastapi import APIRouter, Depends
import urllib.request
import json
from pydantic import BaseModel
from typing import List, Dict
from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.auth.models import User, UserRole
from app.modules.ai.models import AIConfiguration # 🚀 Importado AIConfiguration de forma segura

# 🚀 INSTANCIACIÓN INICIAL: Ahora router se declara antes de que los endpoints lo invoquen
router = APIRouter()

# ==========================================
# ESQUEMAS PYDANTIC (Para la Configuración Multi-Agente)
# ==========================================
class AgentConfigSchema(BaseModel):
    model: str
    system_prompt: str
    protocol_prompt: str
    guardrails_prompt: str

class AIConfigSchema(BaseModel):
    openrouter_api_key: str
    available_models: List[str]
    agent_onboarding_empresa: AgentConfigSchema
    agent_onboarding_proyectos: AgentConfigSchema
    agent_ventas: AgentConfigSchema
    agent_reporteria: AgentConfigSchema

# ==========================================
# RUTAS DE ADMINISTRACIÓN IA (Staff / Admin)
# ==========================================
@router.get("/config")
def get_ai_config(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))):
    """Obtiene la configuración de los 4 agentes y el inventario de modelos."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
    if not config:
        config = AIConfiguration(company_id=current_user.company_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

@router.put("/config")
def update_ai_config(payload: AIConfigSchema, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))):
    """Actualiza la configuración maestra de inteligencia."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
        
    config.openrouter_api_key = payload.openrouter_api_key
    config.available_models = payload.available_models
    config.agent_onboarding_empresa = payload.agent_onboarding_empresa.model_dump()
    config.agent_onboarding_proyectos = payload.agent_onboarding_proyectos.model_dump()
    config.agent_ventas = payload.agent_ventas.model_dump()
    config.agent_reporteria = payload.agent_reporteria.model_dump()
    
    db.commit()
    return {"message": "Configuración Multi-Agente actualizada con éxito."}

@router.get("/config/consumption")
def get_api_consumption(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN]))):
    """Consulta la API de OpenRouter en tiempo real para ver el saldo y límite de la llave configurada."""
    config = db.query(AIConfiguration).filter(AIConfiguration.company_id == current_user.company_id).first()
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
                "limit": key_data.get("limit", None)
            }
    except Exception as e:
        return {"usage": 0, "limit": 0, "error": "Llave inválida o error de conexión"}