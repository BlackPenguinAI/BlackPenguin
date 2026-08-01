from pydantic import BaseModel, ConfigDict, HttpUrl
from typing import Optional, List
from datetime import datetime

class CompanyProfileBase(BaseModel):
    legal_name: Optional[str] = None
    dba: Optional[str] = None
    headquarters: Optional[str] = None
    year_established: Optional[str] = None
    executive_team: Optional[List[dict]] = []
    asset_classes: Optional[List[str]] = []
    market_coverage: Optional[str] = None
    target_demographics: Optional[str] = None
    aum: Optional[str] = None
    investment_strategy: Optional[str] = None
    value_proposition: Optional[str] = None
    key_differentiators: Optional[str] = None
    tone_of_voice: Optional[str] = None
    key_messaging: Optional[str] = None

class CompanyProfileUpdate(CompanyProfileBase):
    pass

class CompanyProfileResponse(CompanyProfileBase):
    id: str
    company_id: str
    is_identity_completed: Optional[bool] = False
    is_team_completed: Optional[bool] = False
    is_focus_completed: Optional[bool] = False
    is_market_completed: Optional[bool] = False
    is_strategy_completed: Optional[bool] = False
    is_value_prop_completed: Optional[bool] = False
    is_brand_completed: Optional[bool] = False
    is_profile_fully_completed: Optional[bool] = False
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class ChatMessagePayload(BaseModel):
    message: str

class ChatMessageResponse(BaseModel):
    sender: str
    content: str
    created_at: datetime
    
class ScrapeRequest(BaseModel):
    url: HttpUrl