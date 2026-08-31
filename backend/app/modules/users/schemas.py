from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Literal, Optional, List
from datetime import datetime
from .models import UserRole

class MyProfileResponse(BaseModel):
    email: str
    role: UserRole
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None      # 🚀 AÑADIDO
    country: Optional[str] = None    # 🚀 AÑADIDO
    timezone: str = "UTC"
    company_name: Optional[str] = None
    plan_name: Optional[str] = None
    license_start: Optional[datetime] = None
    license_end: Optional[datetime] = None

class MyProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None      # 🚀 AÑADIDO
    country: Optional[str] = None    # 🚀 AÑADIDO
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=80)
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
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(min_length=1, max_length=100)
    role: str
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    project_access_scope: Literal["all", "selected"] = "all"
    project_ids: List[str] = Field(default_factory=list)


class TenantUserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[Literal["assistant", "mkt", "sales"]] = None
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=80)
    project_access_scope: Optional[Literal["all", "selected"]] = None
    project_ids: Optional[List[str]] = None


class TenantUserResponse(BaseModel):
    id: str
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    timezone: str = "UTC"
    role: UserRole
    is_active: bool
    project_access_scope: Literal["all", "selected"] = "all"
    project_ids: List[str] = Field(default_factory=list)
    project_assignment_required: bool = False
    auth_status: str = "active"
    invitation_sent_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CompanyProjectOption(BaseModel):
    id: str
    name: str
