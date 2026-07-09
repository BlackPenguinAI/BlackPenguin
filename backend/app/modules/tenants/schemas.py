from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# ==========================================
# ESQUEMAS DE PLANES DE SUSCRIPCIÓN
# ==========================================
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

class SubscriptionPlanUpdate(SubscriptionPlanBase):
    name: Optional[str] = None

class SubscriptionPlanResponse(SubscriptionPlanBase):
    id: str

    class Config:
        from_attributes = True

# ==========================================
# ESQUEMAS DE DESARROLLADORES (ONBOARDING)
# ==========================================
class DeveloperCreate(BaseModel):
    company_name: str
    plan_id: str
    duration_months: int = 12
    admin_email: EmailStr
    admin_first_name: str       # 🚀 NUEVO
    admin_paternal_last_name: str # 🚀 NUEVO
    admin_maternal_last_name: Optional[str] = "" # 🚀 NUEVO
    is_active: bool = True
    language: str = "en"

class DeveloperUpdate(BaseModel):
    company_name: Optional[str] = None
    plan_id: Optional[str] = None
    duration_months: Optional[int] = None
    is_active: Optional[bool] = None
    payment_receipt_url: Optional[str] = None
    admin_email: Optional[EmailStr] = None
    admin_first_name: Optional[str] = None        # 🚀 NUEVO
    admin_paternal_last_name: Optional[str] = None  # 🚀 NUEVO
    admin_maternal_last_name: Optional[str] = None  # 🚀 NUEVO

class DeveloperResponse(BaseModel):
    id: str
    name: str
    license_start: datetime
    license_end: datetime
    plan_duration_months: int
    is_active: bool
    payment_receipt_url: Optional[str] = None
    plan_id: Optional[str] = None
    
    # 🚀 NUEVO: Campos del administrador mapeados en la respuesta
    admin_email: Optional[str] = None
    admin_first_name: Optional[str] = None
    admin_paternal_last_name: Optional[str] = None
    admin_maternal_last_name: Optional[str] = None
    
    class Config:
        from_attributes = True


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

# ==========================================
# ESQUEMAS DEL CHAT DE ONBOARDING
# ==========================================
class ChatMessagePayload(BaseModel):
    message: str

class ChatMessageResponse(BaseModel):
    sender: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class OnboardingSessionStatus(BaseModel):
    id: str
    is_completed: bool
    messages: List[ChatMessageResponse] = []