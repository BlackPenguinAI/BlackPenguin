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
    full_name: str
    phone: str
    email: Optional[str] = None
    source: str
    intent_score: float
    is_opt_out: bool
    funnel_stage: FunnelStage
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

class MeetingResponse(BaseModel):
    id: str
    project_id: str
    lead_id: str
    broker_id: str
    meeting_time: datetime
    status: MeetingStatus
    gcal_event_id: Optional[str] = None
    lead_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class SalesReportResponse(BaseModel):
    inventory_status: str
    total_revenue: float
    target_roi: float
    unit_inventory: List[dict]
    leads_map: List[dict]