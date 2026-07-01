from pydantic import BaseModel
from typing import Optional

class LeadCapturePayload(BaseModel):
    full_name: str
    phone: str
    email: Optional[str] = None
    project_id: str