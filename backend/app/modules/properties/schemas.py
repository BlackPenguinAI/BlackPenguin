from pydantic import BaseModel, ConfigDict
from typing import Optional
import uuid

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

class ProjectResponse(ProjectCreate):
    id: uuid.UUID
    company_id: uuid.UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)