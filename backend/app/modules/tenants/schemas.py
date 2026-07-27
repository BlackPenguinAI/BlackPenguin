from pydantic import BaseModel, EmailStr, HttpUrl, ConfigDict
from typing import Optional, List, Dict
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
# ESQUEMAS DE DESARROLLADORES 
# ==========================================
class DeveloperCreate(BaseModel):
    company_name: str
    plan_id: str
    duration_months: int = 12
    admin_email: EmailStr
    admin_password: str  # 🚀 NUEVO CAMPO: Recibe la contraseña manual
    admin_first_name: str       
    admin_paternal_last_name: str 
    admin_maternal_last_name: Optional[str] = "" 
    is_active: bool = True
    language: str = "en"
    website_url: Optional[str] = None

class DeveloperUpdate(BaseModel):
    company_name: Optional[str] = None
    plan_id: Optional[str] = None
    duration_months: Optional[int] = None
    is_active: Optional[bool] = None
    payment_receipt_url: Optional[str] = None
    admin_email: Optional[EmailStr] = None
    admin_first_name: Optional[str] = None        
    admin_paternal_last_name: Optional[str] = None  
    admin_maternal_last_name: Optional[str] = None  

class DeveloperResponse(BaseModel):
    id: str
    name: str
    license_start: datetime
    license_end: datetime
    plan_duration_months: int
    is_active: bool
    payment_receipt_url: Optional[str] = None
    plan_id: Optional[str] = None
    
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

# =========================================================================
# 🚀 NUEVOS: ESQUEMAS DEL PERFIL COGNITIVO (COMPANY PROFILE)
# =========================================================================
class ExecutiveContactSchema(BaseModel):
    name: str
    role: str
    email: Optional[str] = None

class CompanyProfileBase(BaseModel):
    scraped_source_url: Optional[str] = None
    
    legal_name: Optional[str] = None
    dba: Optional[str] = None
    headquarters: Optional[str] = None
    year_established: Optional[int] = None
    
    #executive_team: List[ExecutiveContactSchema] = []
    executive_team: Optional[List[ExecutiveContactSchema]] = []
    
    asset_classes: List[str] = []
    core_focus_description: Optional[str] = None
    
    market_coverage: Optional[str] = None
    target_demographics: Optional[str] = None
    
    portfolio_size_aum: Optional[str] = None
    investment_strategy: Optional[str] = None
    
    value_proposition: Optional[str] = None
    key_differentiators: Optional[str] = None
    
    tone_of_voice: Optional[str] = None
    key_messaging: Optional[str] = None

class CompanyProfileUpdate(CompanyProfileBase):
    # La IA enviará los campos que haya descubierto
    pass

class CompanyProfileResponse(CompanyProfileBase):
    id: str
    company_id: str
    
    is_identity_completed: bool
    is_team_completed: bool
    is_focus_completed: bool
    is_market_completed: bool
    is_strategy_completed: bool
    is_value_prop_completed: bool
    is_brand_completed: bool
    is_profile_fully_completed: bool
    
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

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