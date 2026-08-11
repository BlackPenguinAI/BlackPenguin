from pydantic import BaseModel, ConfigDict
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

class MeetingResponse(BaseModel):
    id: str
    project_id: str
    lead_id: str
    broker_id: str
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
    lead_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class SalesReportResponse(BaseModel):
    inventory_status: Optional[str] = None
    total_revenue: Optional[float] = None
    target_roi: Optional[float] = None
    unit_inventory: List[dict]
    leads_map: List[dict]
    calculation_status: str = "pending"
    generated_at: Optional[datetime] = None
