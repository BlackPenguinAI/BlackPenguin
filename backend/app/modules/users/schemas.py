from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime
from .models import UserRole

class MyProfileResponse(BaseModel):
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None      # 🚀 AÑADIDO
    country: Optional[str] = None    # 🚀 AÑADIDO
    company_name: Optional[str] = None
    plan_name: Optional[str] = None
    license_start: Optional[datetime] = None
    license_end: Optional[datetime] = None

class MyProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None      # 🚀 AÑADIDO
    country: Optional[str] = None    # 🚀 AÑADIDO
    company_name: Optional[str] = None

class PasswordUpdatePayload(BaseModel):
    current_password: str
    new_password: str

class SetPasswordPayload(BaseModel):
    token: str
    new_password: str

class CompanyBasicResponse(BaseModel):
    id: str
    name: str
    model_config = ConfigDict(from_attributes=True)

class UserAdminListResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    role: str
    is_active: bool
    company_id: Optional[str] = None
    company: Optional[CompanyBasicResponse] = None
    ai_tokens_used: Optional[int] = 0
    ai_cost_usd: Optional[float] = 0.0

    model_config = ConfigDict(from_attributes=True)


class TenantUserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    role: str


class TenantUserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    is_active: Optional[bool] = None


class TenantUserResponse(BaseModel):
    id: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    role: UserRole
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
