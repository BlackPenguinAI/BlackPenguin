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


class ChatAttachmentResponse(BaseModel):
    id: str
    kind: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    status: str
    url: str | None = None
    download_url: str | None = None


class ChatMessageResponse(BaseModel):
    id: str
    sender: str
    content: str
    created_at: datetime
    attachments: list[ChatAttachmentResponse] = Field(default_factory=list)


class NextQuestionResponse(BaseModel):
    field: str | None = None
    label: str
    prompt: str
    input_type: str
    options: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    allow_custom: bool = True
    minimum_words: int | None = None


class RejectedUpdate(BaseModel):
    field: str | None = None
    reason: str


class ChatTurnResponse(BaseModel):
    message: ChatMessageResponse
    user_message: ChatMessageResponse | None = None
    profile: CompanyProfileResponse
    accepted_fields: list[str] = Field(default_factory=list)
    rejected_updates: list[RejectedUpdate] = Field(default_factory=list)
    sources: list["SourceResponse"] = Field(default_factory=list)
    next_question: NextQuestionResponse


class SessionResponse(BaseModel):
    is_completed: bool


class ScrapeRequest(BaseModel):
    url: HttpUrl


SourceKind = Literal[
    "official_website",
    "social_profile",
    "online_document",
    "third_party",
    "uploaded_file",
]
SourceStatus = Literal["processing", "ready", "failed"]
ProposalStatus = Literal["pending", "confirmed", "corrected", "rejected"]


class SourceProposalResponse(BaseModel):
    id: str
    field: str
    label: str
    value: Any = None
    evidence: str | None = None
    confidence: str | None = None
    status: ProposalStatus


class SourceResponse(BaseModel):
    id: str
    kind: SourceKind
    status: SourceStatus
    name: str
    url: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    message_id: str | None = None
    download_url: str | None = None
    error_message: str | None = None
    proposals: list[SourceProposalResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProposalDecision(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value: Any = None


class ProposalDecisionResponse(BaseModel):
    proposal: SourceProposalResponse
    profile: CompanyProfileResponse


class ChatBootstrapRequest(BaseModel):
    initial_url: HttpUrl | None = None
    skip_website: bool = False


class OnboardingStateResponse(BaseModel):
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    profile: CompanyProfileResponse
    sources: list[SourceResponse] = Field(default_factory=list)
    next_question: NextQuestionResponse
    stage: Literal["website", "processing", "review", "conversation", "complete"]
    version: int
