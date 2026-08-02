from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime

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