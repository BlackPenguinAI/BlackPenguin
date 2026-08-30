from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional

class AgentConfigSchema(BaseModel):
    model: str
    system_prompt: str
    protocol_prompt: str
    guardrails_prompt: str
    stage_prompts: Dict[str, str] = Field(default_factory=dict)
    segment_prompts: Dict[str, str] = Field(default_factory=dict)
    objection_prompts: Dict[str, str] = Field(default_factory=dict)
    sms_templates: Dict[str, str] = Field(default_factory=dict)
    scoring_config: Dict[str, Any] = Field(default_factory=dict)
    cadence_config: Dict[str, Any] = Field(default_factory=dict)


class SalesPromptDraftPayload(BaseModel):
    configuration: AgentConfigSchema
    change_note: str = ""

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
