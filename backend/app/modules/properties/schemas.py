from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
import uuid

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

class ProjectProfileResponse(BaseModel):
    is_technical_completed: bool
    is_commercial_completed: bool
    is_inventory_completed: bool
    is_fully_completed: bool
    
    typologies: Optional[List[Any]] = []
    amenities: Optional[List[Any]] = []
    price_from: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ProjectResponse(ProjectCreate):
    id: uuid.UUID
    company_id: uuid.UUID
    is_active: bool
    profile: Optional[ProjectProfileResponse] = None

    model_config = ConfigDict(from_attributes=True)

# Esquemas del Chat
class ChatMessagePayload(BaseModel):
    message: str

class ChatMessageResponse(BaseModel):
    sender: str
    content: str