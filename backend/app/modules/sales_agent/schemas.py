from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class SimulationRequest(BaseModel):
    lead_id: str
    message: str = Field(min_length=1, max_length=5000)
    event_id: str | None = None


class SimulationLeadForm(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=7, max_length=30)
    email: EmailStr
    product_id: str = Field(min_length=3, max_length=260)
    budget_min: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    budget_max: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2)
    consent: bool
    custom_answers: dict[str, Any] = Field(default_factory=dict)

    @field_validator("first_name", "last_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("First and last name are required.")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        compact = "".join(character for character in value if character.isdigit() or character == "+")
        if len([character for character in compact if character.isdigit()]) < 7:
            raise ValueError("Enter a valid phone number.")
        return compact

    @model_validator(mode="after")
    def validate_budget_range(self):
        if self.budget_max is not None and self.budget_max < self.budget_min:
            raise ValueError("Maximum budget must be greater than or equal to minimum budget.")
        return self


class SimulationCreate(BaseModel):
    project_id: str
    campaign_id: str
    lead: SimulationLeadForm


class SimulationApproval(BaseModel):
    status: str = Field(pattern="^(approved|changes_requested|rejected)$")
    notes: str | None = Field(default=None, max_length=4000)


class SimulationAdvance(BaseModel):
    hours: int = Field(ge=1, le=720)


class AppointmentConfirm(BaseModel):
    start_at: datetime
    duration_minutes: int = Field(default=45, ge=15, le=240)
    modality: str = Field(default="virtual", pattern="^(virtual|phone|showroom|in_person)$")


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
    campaign_name: str | None = None
    simulation_id: str | None = None
    simulation_status: str | None = None
    approval_status: str | None = None
    virtual_now: datetime | None = None
    appointment_id: str | None = None
    assigned_sales_user_id: str | None = None
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


class SimulationOptionCampaign(BaseModel):
    id: str
    name: str
    status: str
    objective: str | None = None


class SimulationOptionProduct(BaseModel):
    id: str
    name: str
    code: str | None = None
    description: str | None = None
    bedrooms: int | None = None
    bathrooms: float | None = None
    area_min: float | None = None
    area_max: float | None = None
    area_unit: str | None = None
    available_units: int | None = None
    total_units: int | None = None
    starting_price: float | None = None
    maximum_price: float | None = None
    currency: str | None = None
    inventory_updated_at: datetime | None = None


class SimulationOptionProject(BaseModel):
    id: str
    name: str
    onboarding_status: str
    campaigns: list[SimulationOptionCampaign]
    products: list[SimulationOptionProduct]
    delivery_timeline: str | None = None
    eligible_sales_users: int


class AppointmentSlot(BaseModel):
    start_at: datetime
    end_at: datetime
    eligible_sales_users: int


class SimulationCreateResponse(BaseModel):
    simulation_id: str
    lead_id: str
    conversation_id: str
    status: str
    initial_reply: str | None = None
    prompt_snapshot: dict[str, Any] = Field(default_factory=dict)
    requires_initial_message: bool = True


class AppointmentConfirmationResponse(BaseModel):
    meeting_id: str
    assigned_sales_user_id: str
    assigned_sales_name: str
    meeting_time: datetime
    calendar_sync_status: str
