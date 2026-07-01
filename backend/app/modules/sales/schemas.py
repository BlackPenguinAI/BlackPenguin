from pydantic import BaseModel, ConfigDict
from typing import Optional
import uuid
from datetime import datetime
from app.modules.sales.models import FunnelStage

class LeadResponse(BaseModel):
    id: uuid.UUID
    project_id: Optional[uuid.UUID]
    full_name: str
    phone: str
    email: Optional[str]
    source: str
    intent_score: float
    is_opt_out: bool
    funnel_stage: FunnelStage
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LeadUpdate(BaseModel):
    funnel_stage: FunnelStage