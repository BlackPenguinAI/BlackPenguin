from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

# Schema para la respuesta. (La creación es vía Form Data, no Pydantic)
class CompanyResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    license_start: datetime
    license_end: datetime
    payment_receipt_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)