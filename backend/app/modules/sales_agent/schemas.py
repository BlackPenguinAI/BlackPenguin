from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SimulationRequest(BaseModel):
    lead_id: str
    message: str = Field(min_length=1, max_length=5000)
    event_id: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    conversation_id: str
    status: str
    mode: str
    reply: str | None = None
    intent: str | None = None
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    requires_human: bool
    policy_violations: list[str] = Field(default_factory=list)
    draft_id: str | None = None


class ConversationSummary(BaseModel):
    id: str
    lead_id: str
    project_id: str
    campaign_id: str | None = None
    channel: str
    stage: str
    automation_level: int
    is_paused: bool
    updated_at: datetime
    lead_name: str
    phone: str
    funnel_stage: str
    intent_score: float = 0
    last_message: str | None = None
    last_message_at: datetime | None = None
    next_action_at: datetime | None = None
    agent_status: str = "simulation"
    project_name: str
    is_demo: bool = False
    model_config = ConfigDict(from_attributes=True)


class SalesMessageResponse(BaseModel):
    id: str
    conversation_id: str
    direction: str
    role: str
    content: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConversationAction(BaseModel):
    action: str = Field(pattern="^(pause|resume|human_handoff)$")


class DraftDecision(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    reason: str | None = None
