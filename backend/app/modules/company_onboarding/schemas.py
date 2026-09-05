from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator


ValidationStatus = Literal[
    "missing",
    "extracted",
    "pending_confirmation",
    "confirmed",
    "corrected_by_user",
    "conflicting",
    "not_applicable",
    "deferred",
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


class CompanyMediaAssetResponse(BaseModel):
    id: str
    role: str
    name: str
    mime_type: str
    size_bytes: int
    source_url: str | None = None
    is_primary: bool
    review_status: str
    image_url: str
    created_at: datetime


class CompanyOverviewResponse(BaseModel):
    company_id: str
    name: str
    legal_name: str | None = None
    description: str | None = None
    headquarters: str | None = None
    business_model: Any = None
    asset_classes: Any = None
    operating_footprint: Any = None
    public_contacts: dict[str, Any] = Field(default_factory=dict)
    logo_url: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    completion: CompletionSummary
    updated_at: datetime | None = None


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
    in_reply_to_message_id: str | None = None


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
    ui_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    in_reply_to_message_id: str | None = None


class NextQuestionResponse(BaseModel):
    field: str | None = None
    label: str
    prompt: str
    input_type: str
    options: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    allow_custom: bool = True
    minimum_words: int | None = None
    minimum_characters: int | None = None
    help_text: str | None = None
    answer_actions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    suggestion_origin: Literal["website", "confirmed_context", "generic_fallback"] | None = None
    suggestion_sources: list[str] = Field(default_factory=list)


class RejectedUpdate(BaseModel):
    field: str | None = None
    reason: str


class ChatTurnResponse(BaseModel):
    request_id: str | None = None
    message_saved: bool = True
    profile_changed: bool = False
    field_update_status: Literal["accepted", "rejected", "not_applicable"] = "not_applicable"
    assistant_status: Literal["deterministic", "llm", "fallback"] = "deterministic"
    source_actions: list[dict[str, Any]] = Field(default_factory=list)
    message: ChatMessageResponse
    user_message: ChatMessageResponse | None = None
    profile: CompanyProfileResponse
    accepted_fields: list[str] = Field(default_factory=list)
    rejected_updates: list[RejectedUpdate] = Field(default_factory=list)
    sources: list["SourceResponse"] = Field(default_factory=list)
    next_question: NextQuestionResponse | None = None


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
    processing_stage: Literal[
        "queued", "connecting", "reading", "extracting", "identifying", "preparing", "complete", "failed"
    ] = "queued"
    processing_detail: str | None = None
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
    next_question: NextQuestionResponse | None = None
    stage: Literal[
        "website", "processing", "website_review", "logo_review", "required", "team",
        "conditional", "enrichment", "approval", "complete",
    ]
    version: int
    team: "TeamOnboardingResponse"


TeamRole = Literal["assistant", "mkt", "sales"]
TeamRoleStatus = Literal["missing", "confirmed", "deferred", "not_applicable"]


class TeamMemberCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: TeamRole
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    project_access_scope: Literal["all", "selected"] = "all"
    project_ids: list[str] = Field(default_factory=list)

    @field_validator("first_name", "last_name")
    @classmethod
    def names_must_not_be_blank(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Name fields cannot be blank.")
        return normalized


class TeamMemberResponse(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str
    role: str
    is_active: bool
    auth_status: str = "active"
    invitation_sent_at: datetime | None = None
    invitation_status: str | None = None
    invitation_delivery: Literal["sent", "failed", "pending", "not_applicable"] = "not_applicable"
    invitation_error_code: str | None = None
    invitation_error_message: str | None = None
    request_replayed: bool = False


class TeamRoleProgress(BaseModel):
    role: TeamRole
    label: str
    status: TeamRoleStatus
    active_users: int
    pending_users: int = 0
    failed_users: int = 0


class TeamOnboardingResponse(BaseModel):
    administrator: TeamMemberResponse | None = None
    members: list[TeamMemberResponse] = Field(default_factory=list)
    roles: list[TeamRoleProgress] = Field(default_factory=list)
    projects: list[dict[str, str]] = Field(default_factory=list)


class TeamRoleDecision(BaseModel):
    status: Literal["deferred", "not_applicable"]


OnboardingStateResponse.model_rebuild()
