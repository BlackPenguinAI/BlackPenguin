from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
from .models import FunnelStage, MeetingStatus

class SmsChatMessageSchema(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class LeadResponse(BaseModel):
    id: str
    project_id: Optional[str] = None
    campaign_id: Optional[str] = None
    assigned_sales_user_id: Optional[str] = None
    full_name: str
    phone: str
    email: Optional[str] = None
    source: str
    platform: str = "manual"
    preferred_channel: Optional[str] = None
    consent_status: str = "unknown"
    intent_score: float
    is_opt_out: bool
    funnel_stage: FunnelStage
    qualification_summary: Optional[str] = None
    agent_status: str = "paused"
    last_interaction_at: Optional[datetime] = None
    stage_changed_at: Optional[datetime] = None
    next_action_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SalesLeadDetailResponse(LeadResponse):
    project_name: Optional[str] = None
    campaign_name: Optional[str] = None
    conversation_id: Optional[str] = None
    meta_form_data: dict = Field(default_factory=dict)
    chat_summary: Optional[str] = None
    visit_recommendations: Optional[str] = None

class LeadUpdate(BaseModel):
    funnel_stage: FunnelStage

class MeetingCreate(BaseModel):
    project_id: str
    lead_id: str
    broker_id: str
    meeting_time: datetime
    duration_minutes: int = 45
    modality: str = "virtual"
    notes: Optional[str] = None

class MeetingUpdate(BaseModel):
    broker_id: Optional[str] = None
    status: Optional[MeetingStatus] = None
    confirmation_status: Optional[str] = None
    modality: Optional[str] = None
    notes: Optional[str] = None

class MeetingResponse(BaseModel):
    id: str
    project_id: str
    lead_id: str
    broker_id: Optional[str] = None
    assigned_sales_user_id: Optional[str] = None
    meeting_time: datetime
    duration_minutes: int = 45
    modality: str = "virtual"
    confirmation_status: str = "pending"
    calendar_sync_status: str = "not_connected"
    meeting_url: Optional[str] = None
    notes: Optional[str] = None
    status: MeetingStatus
    gcal_event_id: Optional[str] = None
    is_demo: bool = False
    source: str = "manual"
    lead_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AvailabilityWindowInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    is_active: bool = True

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time.")
        return self


class AvailabilityUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=80)
    windows: List[AvailabilityWindowInput] = Field(default_factory=list, max_length=21)


class AvailabilityWindowResponse(AvailabilityWindowInput):
    id: str
    timezone: str
    model_config = ConfigDict(from_attributes=True)


class AvailabilityBlockCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("End time must be after start time.")
        if (self.ends_at - self.starts_at).total_seconds() > 24 * 60 * 60:
            raise ValueError("An availability block cannot exceed 24 hours.")
        return self


class AvailabilityBlockResponse(AvailabilityBlockCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class SalesScheduleResponse(BaseModel):
    availability: List[AvailabilityBlockResponse]
    meetings: List[MeetingResponse]


class CalendarConnectionUpdate(BaseModel):
    provider: str = Field(pattern="^(google|outlook|simulation)$")
    calendar_id: str = Field(min_length=1, max_length=255)


class CalendarConnectionResponse(BaseModel):
    provider: str
    calendar_id: Optional[str] = None
    status: str
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class SalesReportResponse(BaseModel):
    inventory_status: Optional[str] = None
    total_revenue: Optional[float] = None
    target_roi: Optional[float] = None
    unit_inventory: List[dict]
    leads_map: List[dict]
    calculation_status: str = "pending"
    generated_at: Optional[datetime] = None
