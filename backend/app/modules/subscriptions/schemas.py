from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class SubscriptionPlanBase(BaseModel):
    name: str
    description: Optional[str] = None
    max_assistants: int = 0
    max_mkt_users: int = 0
    max_sales_users: int = 0
    max_projects: int = 1
    max_property_types_per_project: int = 20
    max_properties_per_project: int = 50
    is_active: bool = True

# Renombrados para compatibilidad exacta con el Router
class PlanCreate(SubscriptionPlanBase):
    pass

class PlanResponse(SubscriptionPlanBase):
    id: str
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
