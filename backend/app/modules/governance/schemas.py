from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReasonPayload(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class UserStatusPayload(ReasonPayload):
    action: Literal["suspend", "reactivate"]


class DeletePayload(ReasonPayload):
    confirmation: str = Field(min_length=1, max_length=220)


class OperatingPolicyPayload(BaseModel):
    project_id: str | None = None
    timezone: str = Field(min_length=1, max_length=80)
    weekly_windows: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    blackout_dates: list[str] = Field(default_factory=list)
    enforce_manual_messages: bool = False
    is_enabled: bool = True


class OperatingPolicyResponse(OperatingPolicyPayload):
    id: str
    company_id: str
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GuidanceItemPayload(BaseModel):
    project_id: str | None = None
    kind: Literal["faq", "script"]
    title: str = Field(min_length=2, max_length=220)
    content: str = Field(min_length=2, max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["draft", "approved", "archived"] = "draft"


class GuidanceItemResponse(GuidanceItemPayload):
    id: str
    company_id: str
    version: int
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class KpiTargetPayload(BaseModel):
    project_id: str | None = None
    response_rate_percent: int = Field(ge=0, le=100)
    conversation_turns_min: int = Field(ge=0, le=1000)
    conversation_turns_max: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def validate_turns(self):
        if self.conversation_turns_max < self.conversation_turns_min:
            raise ValueError("Maximum turns must be greater than or equal to minimum turns.")
        return self


class KpiTargetResponse(KpiTargetPayload):
    id: str
    company_id: str
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    id: str
    notification_type: str
    severity: str
    title: str
    body: str
    entity_type: str | None = None
    entity_id: str | None = None
    action_url: str | None = None
    read_at: datetime | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AuditEventResponse(BaseModel):
    id: str
    company_id: str | None = None
    actor_user_id: str | None = None
    actor_role: str
    export_type: str
    filters_json: dict[str, Any]
    record_count: int
    content_hash: str | None = None
    outcome: str
    request_id: str | None = None
    event_hash: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
