from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


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
    timezone: str = Field(default="UTC", min_length=1, max_length=80)


class ProjectTimezoneUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=80)


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
    project_name: str
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


class ProjectOnboardingActionRequest(BaseModel):
    action: Literal[
        "authorize_ai_sales",
        "complete_sales_team",
        "defer_sales_team",
        "complete_meta_setup",
        "defer_meta_setup",
    ]
    question_message_id: str
    client_action_id: str = Field(min_length=36, max_length=36)
    page_id: str | None = Field(default=None, min_length=5, max_length=32)
    ad_account_id: str | None = Field(default=None, min_length=5, max_length=36)
    lead_form_id: str | None = Field(default=None, min_length=5, max_length=32)
    page_access_confirmed: bool = False
    ad_account_access_confirmed: bool = False
    leads_access_confirmed: bool = False


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
    validation: dict[str, Any] | None = None


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
    id: str | None = None
    typology: str
    total: int | None = None
    sold: int | None = None
    available: int | None = None
    starting_price: float | None = None
    currency: str | None = None
    description: str | None = None
    bedrooms: int | None = None
    bathrooms: float | None = None
    area_min: float | None = None
    area_max: float | None = None
    area_unit: str | None = None
    images_status: str = "pending"
    images: list[str] = Field(default_factory=list)


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


class PropertyTypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    code: str | None = Field(default=None, max_length=100)
    description: str | None = None
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    bathrooms: float | None = Field(default=None, ge=0, le=50)
    area_min: float | None = Field(default=None, ge=0)
    area_max: float | None = Field(default=None, ge=0)
    area_unit: str | None = Field(default=None, max_length=20)
    total_units: int | None = Field(default=None, ge=0)
    available_units: int | None = Field(default=None, ge=0)
    starting_price: float | None = Field(default=None, ge=0)
    maximum_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=10)
    features: list[str] = Field(default_factory=list)
    inventory_updated_at: datetime | None = None
    images_status: Literal["pending", "provided", "deferred"] = "pending"
    source_reference: str | None = None
    sort_order: int = 0

    @field_validator("inventory_updated_at", mode="after")
    @classmethod
    def normalize_inventory_updated_at(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.area_min is not None and self.area_max is not None and self.area_min > self.area_max:
            raise ValueError("Area minimum cannot be greater than area maximum.")
        if self.total_units is not None and self.available_units is not None and self.available_units > self.total_units:
            raise ValueError("Available units cannot be greater than total units.")
        if self.starting_price is not None and self.maximum_price is not None and self.starting_price > self.maximum_price:
            raise ValueError("Starting price cannot be greater than maximum price.")
        if self.currency:
            self.currency = self.currency.upper()
        return self


class PropertyTypeCreate(PropertyTypeBase):
    review_status: Literal["candidate", "confirmed"] = "confirmed"


class PropertyTypeUpdate(PropertyTypeBase):
    review_status: Literal["candidate", "confirmed", "rejected"] = "confirmed"


class PropertyTypeMediaResponse(BaseModel):
    id: str
    source_id: str
    caption: str | None = None
    sort_order: int
    image_url: str


class PropertyTypeResponse(PropertyTypeBase):
    id: str
    project_id: str
    review_status: Literal["candidate", "confirmed", "rejected"]
    is_complete: bool
    media: list[PropertyTypeMediaResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PropertyTypeMediaAttach(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=20)


class PropertyTypeCatalogResponse(BaseModel):
    items: list[PropertyTypeResponse]
    confirmed_count: int
    candidate_count: int
    limit: int
    remaining: int
    catalog_complete: bool


class ProjectMarketingCampaignMetric(BaseModel):
    id: str
    name: str
    platform: str
    status: str
    leads: int
    qualified: int
    appointments: int
    conversion_rate: float


class ProjectMarketingSummary(BaseModel):
    project_id: str
    project_name: str
    totals: dict[str, int | float]
    campaigns: list[ProjectMarketingCampaignMetric]
    leads: list[dict[str, Any]]


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
