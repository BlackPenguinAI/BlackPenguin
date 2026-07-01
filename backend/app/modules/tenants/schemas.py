from pydantic import BaseModel
from app.modules.tenants.models import PlanTier

class ProvisionCompanyRequest(BaseModel):
    name: str
    plan_tier: PlanTier # 'core' o 'enterprise'
    admin_email: str
    admin_password: str