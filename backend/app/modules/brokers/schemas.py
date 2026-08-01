from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional

class BrokerCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    google_calendar_id: Optional[str] = None

class BrokerResponse(BrokerCreate):
    id: str
    project_id: str
    model_config = ConfigDict(from_attributes=True)