from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime

# Schema simplificado para el plan anidado
class PlanBasicResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

# Schema simplificado para el usuario administrador anidado
class UserBasicResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class CompanyResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    license_start: datetime
    license_end: datetime
    payment_receipt_url: Optional[str] = None
    plan_id: Optional[str] = None
    created_at: Optional[datetime] = None
    
    plan: Optional[PlanBasicResponse] = None
    users: List[UserBasicResponse] = []
    
    model_config = ConfigDict(from_attributes=True)