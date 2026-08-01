from pydantic import BaseModel, EmailStr, ConfigDict
from datetime import datetime

class WaitlistRequest(BaseModel):
    email: EmailStr
    language: str = "en"

class WaitlistResponse(BaseModel):
    id: str
    email: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)