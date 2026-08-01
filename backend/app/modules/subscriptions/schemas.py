from pydantic import BaseModel, ConfigDict
from typing import Optional

class SubscriptionPlanBase(BaseModel):
    name: str
    description: Optional[str] = None
    max_admins: int = 1
    max_mkt_users: int = 0
    max_sales_users: int = 0
    max_projects: int = 1
    max_properties_per_project: int = 50
    is_active: bool = True

class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass

class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    max_mkt_users: Optional[int] = None
    max_sales_users: Optional[int] = None
    max_projects: Optional[int] = None
    max_properties_per_project: Optional[int] = None
    is_active: Optional[bool] = None

class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: str
    model_config = ConfigDict(from_attributes=True)