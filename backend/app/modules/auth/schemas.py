from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date

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