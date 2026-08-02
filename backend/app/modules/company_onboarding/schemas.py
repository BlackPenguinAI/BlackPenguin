from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ValidationStatus = Literal[
    "missing",
    "extracted",
    "pending_confirmation",
    "confirmed",
    "corrected_by_user",
    "conflicting",
    "not_applicable",
]
Requirement = Literal["required", "conditionally_required", "recommended", "optional"]


class FieldProgress(BaseModel):
    key: str
    label: str
    requirement: Requirement
    status: ValidationStatus
    applicable: bool | None = None


class ProgressCount(BaseModel):
    completed: int
    total: int
    remaining: int


class ConditionalProgress(BaseModel):
    completed: int
    total: int
    evaluated: int
    applicable: int
    remaining: int


class EnrichmentProgress(BaseModel):
    captured: int
    total: int


class CompletionBlocker(BaseModel):
    field: str
    label: str
    status: str


class CompletionSummary(BaseModel):
    percentage: int
    can_complete: bool
    final_approved: bool
    required: ProgressCount
    conditional: ConditionalProgress
    recommended: EnrichmentProgress
    optional: EnrichmentProgress
    blockers: list[CompletionBlocker] = Field(default_factory=list)


class CompanyProfileResponse(BaseModel):
    id: str
    company_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    fields: list[FieldProgress] = Field(default_factory=list)
    completion: CompletionSummary
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FieldUpdate(BaseModel):
    field: str
    value: Any = None
    status: ValidationStatus
    applicable: bool | None = None
    source_type: str | None = None
    source_reference: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None


class CompanyProfilePatch(BaseModel):
    updates: list[FieldUpdate] = Field(default_factory=list)
    final_approved: bool | None = None


class ChatMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class ChatMessageResponse(BaseModel):
    sender: str
    content: str
    created_at: datetime


class SessionResponse(BaseModel):
    is_completed: bool


class ScrapeRequest(BaseModel):
    url: HttpUrl
