from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssignmentUpsert(BaseModel):
    user_id: str
    responsibility: Literal["marketing", "sales"]
    is_primary: bool = False
    routing_weight: int = Field(default=100, ge=0, le=1000)
    accepts_new_leads: bool = True
    is_active: bool = True


class AssignmentResponse(AssignmentUpsert):
    id: str
    project_id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    model_config = ConfigDict(from_attributes=True)
