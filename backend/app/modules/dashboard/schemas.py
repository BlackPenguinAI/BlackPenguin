from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MetricCount(BaseModel):
    active: int | None = None
    current_month: int | None = None


class DashboardStats(BaseModel):
    projects: MetricCount
    leads: MetricCount
    ai_interactions: MetricCount
    generated_at: datetime
    projects_count: int
    leads_count: int
    ai_interactions_count: int
    sales: dict | None = None


SetupStepId = Literal["company", "project", "availability", "lead"]
SetupStepStatus = Literal["complete", "current", "locked"]


class SetupProgressStep(BaseModel):
    id: SetupStepId
    label: str
    status: SetupStepStatus
    url: str
    entity_id: str | None = None
    detail: str


class SetupProgress(BaseModel):
    current_step: SetupStepId | Literal["complete"]
    next_url: str
    is_complete: bool
    steps: list[SetupProgressStep]
