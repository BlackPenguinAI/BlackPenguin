from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ValidationStatus = Literal[
    "missing", "extracted", "pending_confirmation", "confirmed", "corrected_by_user",
    "conflicting", "stale", "expired", "not_applicable",
]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None


class ProjectFieldProgress(BaseModel):
    key: str
    label: str
    section: str
    requirement: str
    status: ValidationStatus
    applicable: bool | None = None


class SectionProgress(BaseModel):
    key: str
    label: str
    completed: int
    total: int
    percentage: int


class ProjectCompletion(BaseModel):
    percentage: int
    can_complete: bool
    final_approved: bool
    completed: int
    total: int
    remaining: int
    sections: list[SectionProgress] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    sales_activation_status: str
    sales_activation_blockers: list[dict[str, Any]] = Field(default_factory=list)


class ProjectProfileResponse(BaseModel):
    id: str
    project_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    fields: list[ProjectFieldProgress] = Field(default_factory=list)
    completion: ProjectCompletion
    updated_at: datetime | None = None


class ProjectResponse(ProjectCreate):
    id: str
    company_id: str
    is_active: bool
    profile: ProjectProfileResponse | None = None
    model_config = ConfigDict(from_attributes=True)


class FieldUpdate(BaseModel):
    field: str
    value: Any = None
    status: ValidationStatus
    applicable: bool | None = None
    source_type: str | None = None
    source_reference: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None


class ProjectProfilePatch(BaseModel):
    updates: list[FieldUpdate] = Field(default_factory=list)
    final_approved: bool | None = None


class ChatMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class ChatMessageResponse(BaseModel):
    sender: str
    content: str
    created_at: datetime


class SourceProposalResponse(BaseModel):
    id: str
    field: str
    label: str
    value: Any = None
    evidence: str | None = None
    confidence: str | None = None
    status: str


class SourceResponse(BaseModel):
    id: str
    kind: str
    status: str
    name: str
    url: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    error_message: str | None = None
    proposals: list[SourceProposalResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatTurnResponse(BaseModel):
    message: ChatMessageResponse
    profile: ProjectProfileResponse
    accepted_fields: list[str] = Field(default_factory=list)
    rejected_updates: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[SourceResponse] = Field(default_factory=list)


class UrlSourceRequest(BaseModel):
    url: HttpUrl


class ProposalDecision(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value: Any = None


class ProposalDecisionResponse(BaseModel):
    proposal: SourceProposalResponse
    profile: ProjectProfileResponse


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    platform: str = "meta"
    objective: str | None = None
    status: Literal["draft", "active", "paused", "archived"] = "draft"
    external_campaign_id: str | None = None
    lead_form_id: str | None = None
    audience_notes: str | None = None
    meta_connection_id: str | None = None


class CampaignResponse(CampaignCreate):
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MetaConnectionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    access_token: str = Field(min_length=20, max_length=4096)
    business_account_id: str | None = None
    ad_account_id: str | None = None
    page_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class MetaConnectionResponse(BaseModel):
    id: str
    label: str
    business_account_id: str | None = None
    ad_account_id: str | None = None
    page_id: str | None = None
    token_hint: str
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    verified_at: datetime | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
