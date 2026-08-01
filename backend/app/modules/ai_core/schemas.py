from pydantic import BaseModel, ConfigDict
from typing import List, Optional

class AgentConfigSchema(BaseModel):
    model: str
    system_prompt: str
    protocol_prompt: str
    guardrails_prompt: str

class AIConfigUpdatePayload(BaseModel):
    openrouter_api_key: Optional[str] = None
    available_models: Optional[List[str]] = None
    
    agent_onboarding_empresa: Optional[AgentConfigSchema] = None
    agent_onboarding_proyectos: Optional[AgentConfigSchema] = None 
    agent_ventas: Optional[AgentConfigSchema] = None
    agent_reporteria: Optional[AgentConfigSchema] = None

class AIConfigResponse(AIConfigUpdatePayload):
    id: str
    model_config = ConfigDict(from_attributes=True)