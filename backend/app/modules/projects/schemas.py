from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ValidationStatus = Literal[
    "missing", "extracted", "pending_confirmation", "confirmed", "corrected_by_user",
    "conflicting", "stale", "expired", "not_applicable", "deferred",
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
    required_fields_complete: bool
    ready_for_confirmation: bool
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
    is_demo: bool = False
    demo_template_version: str | None = None
    onboarding_status: str
    profile: ProjectProfileResponse | None = None
    model_config = ConfigDict(from_attributes=True)


class ProjectDeletionImpact(BaseModel):
    can_delete: bool
    leads: int
    meetings: int
    campaigns: int
    active_campaigns: int
    brokers: int
    sources: int
    files: int
    recommended_action: Literal["delete", "archive"]


class ProjectDeleteRequest(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=150)


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
    in_reply_to_message_id: str | None = None
    client_message_id: str | None = Field(default=None, min_length=36, max_length=36)


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
    message_id: str | None = None
    download_url: str | None = None
    error_message: str | None = None
    is_primary: bool = False
    proposals: list[SourceProposalResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChatTurnResponse(BaseModel):
    request_id: str | None = None
    message_saved: bool = True
    profile_changed: bool = False
    field_update_status: Literal["accepted", "rejected", "not_applicable"] = "not_applicable"
    assistant_status: Literal["deterministic", "llm", "fallback"] = "deterministic"
    redirect_url: str | None = None
    message: ChatMessageResponse
    user_message: ChatMessageResponse | None = None
    profile: ProjectProfileResponse
    accepted_fields: list[str] = Field(default_factory=list)
    rejected_updates: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[SourceResponse] = Field(default_factory=list)
    next_question: NextQuestionResponse


class UrlSourceRequest(BaseModel):
    url: HttpUrl


class ProposalDecision(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value: Any = None


class ProposalDecisionResponse(BaseModel):
    proposal: SourceProposalResponse
    profile: ProjectProfileResponse


class ChatBootstrapRequest(BaseModel):
    initial_url: HttpUrl | None = None
    skip_website: bool = False


class OnboardingStateResponse(BaseModel):
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    profile: ProjectProfileResponse
    sources: list[SourceResponse] = Field(default_factory=list)
    next_question: NextQuestionResponse
    stage: Literal["website", "processing", "review", "conversation", "awaiting_confirmation", "complete"]
    version: int


class ProjectDraftResponse(BaseModel):
    id: str
    onboarding_url: str
    onboarding_status: str


class ProjectCompleteResponse(BaseModel):
    completed: bool
    redirect_url: str
    profile: ProjectProfileResponse


class ProjectOverviewMetric(BaseModel):
    key: str
    label: str
    value: Any = None
    display_value: str
    status: Literal["available", "pending"]


class ProjectInventorySummary(BaseModel):
    typology: str
    total: int | None = None
    sold: int | None = None
    available: int | None = None
    starting_price: float | None = None
    currency: str | None = None


class ProjectOverviewResponse(BaseModel):
    id: str
    name: str
    status: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    delivery_dates: Any = None
    cover_image_url: str | None = None
    cover_focal_point: dict[str, float] = Field(default_factory=dict)
    metrics: list[ProjectOverviewMetric] = Field(default_factory=list)
    inventory: list[ProjectInventorySummary] = Field(default_factory=list)
    location: dict[str, Any] = Field(default_factory=dict)
    market_intelligence: dict[str, Any] = Field(default_factory=dict)
    data_completeness: dict[str, Any] = Field(default_factory=dict)


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
    token_hint: str | None = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    verified_at: datetime | None = None
    verification_mode: Literal["simulated", "real"] = "real"
    verification_status: Literal["pending", "running", "succeeded", "failed"] = "pending"
    simulated_verified_at: datetime | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MetaProjectSetupRequest(BaseModel):
    page_id: str = Field(min_length=5, max_length=32)
    ad_account_id: str = Field(min_length=5, max_length=36)
    lead_form_id: str = Field(min_length=5, max_length=32)
    page_access_confirmed: bool
    ad_account_access_confirmed: bool
    leads_access_confirmed: bool


class MetaProjectSetupResponse(BaseModel):
    connection: MetaConnectionResponse
    campaign: CampaignResponse
    simulated: bool = True
    success: bool = True
    message: str
    partner_business_manager_id: str | None = None


class MetaSetupConfigurationResponse(BaseModel):
    partner_business_manager_id: str | None = None
    configured: bool
