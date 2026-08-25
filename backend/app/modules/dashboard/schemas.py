from datetime import datetime
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
