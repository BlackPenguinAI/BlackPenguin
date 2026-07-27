from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date
from datetime import datetime

class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    last_name_paternal: Optional[str] = None
    last_name_maternal: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    birth_date: Optional[date] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None

class UserProfileResponse(UserProfileUpdate):
    id: str
    email: EmailStr
    role: str
    class Config:
        from_attributes = True

class MyProfileResponse(BaseModel):
    # Datos de Usuario
    email: str
    full_name: Optional[str] = None
    last_name_paternal: Optional[str] = None
    last_name_maternal: Optional[str] = None
    
    # Datos de la Compañía
    company_name: Optional[str] = None
    plan_name: Optional[str] = None
    license_start: Optional[datetime] = None
    license_end: Optional[datetime] = None

class MyProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    last_name_paternal: Optional[str] = None
    last_name_maternal: Optional[str] = None
    company_name: Optional[str] = None