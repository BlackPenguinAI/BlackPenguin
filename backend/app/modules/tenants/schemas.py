from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CompanyBase(BaseModel):
    name: str
    plan_tier: str
    max_projects_allowed: int = 3
    has_voice_agents: bool = False
    has_enterprise_integrations: bool = False
    offline_payment_verified: bool = False
    is_active: bool = True

class CompanyCreate(CompanyBase):
    license_end: datetime

class CompanyUpdate(CompanyBase):
    name: Optional[str] = None
    plan_tier: Optional[str] = None
    license_end: Optional[datetime] = None

class CompanyResponse(CompanyBase):
    id: str
    license_start: datetime
    license_end: datetime

    class Config:
        from_attributes = True