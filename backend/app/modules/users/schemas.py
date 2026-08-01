from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime

class MyProfileResponse(BaseModel):
    email: str
    full_name: Optional[str] = None
    last_name_paternal: Optional[str] = None
    last_name_maternal: Optional[str] = None
    company_name: Optional[str] = None
    plan_name: Optional[str] = None
    license_start: Optional[datetime] = None
    license_end: Optional[datetime] = None

class MyProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    last_name_paternal: Optional[str] = None
    last_name_maternal: Optional[str] = None
    company_name: Optional[str] = None

class PasswordUpdatePayload(BaseModel):
    current_password: str
    new_password: str

class SetPasswordPayload(BaseModel):
    token: str
    new_password: str