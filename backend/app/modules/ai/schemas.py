from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict
from app.modules.ai.models import MongoChatMessage

class ConversationCreatePayload(BaseModel):
    lead_id: str
    agent_type: str
    messages: List[MongoChatMessage]
    total_tokens_used: int = 0

class InteractiveChatRequest(BaseModel):
    lead_id: str
    message: str

class InteractiveChatResponse(BaseModel):
    status: str
    response: str

# =========================================================================
# 🚀 NUEVOS ESQUEMAS: CONFIGURACIÓN DE AGENTES IA (Para el Panel Admin)
# =========================================================================
class AgentConfigSchema(BaseModel):
    model: str
    system_prompt: str
    protocol_prompt: str
    guardrails_prompt: str

class AIConfigUpdatePayload(BaseModel):
    openrouter_api_key: Optional[str] = None
    available_models: Optional[List[str]] = None
    
    # Todos los agentes soportados por tu DB
    agent_onboarding_empresa: Optional[AgentConfigSchema] = None
    agent_onboarding_proyectos: Optional[AgentConfigSchema] = None # Con 's'
    agent_ventas: Optional[AgentConfigSchema] = None
    agent_reporteria: Optional[AgentConfigSchema] = None

class AIConfigResponse(AIConfigUpdatePayload):
    id: str
    model_config = ConfigDict(from_attributes=True)