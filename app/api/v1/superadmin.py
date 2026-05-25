from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.models.pg_models import Company, User, get_db, PlanTier, UserRole
from app.core.security import get_password_hash
from app.core.rbac import require_superadmin
from datetime import date, datetime

router = APIRouter()

class ProvisionCompanyRequest(BaseModel):
    name: str
    plan_tier: PlanTier # core o enterprise
    admin_email: str
    admin_password: str

@router.post("/companies/", dependencies=[Depends(require_superadmin)])
def provision_new_tenant(data: ProvisionCompanyRequest, db: Session = Depends(get_db)):
    # 1. Reglas lógicas del Plan según Pricing Columns
    if data.plan_tier == PlanTier.ENTERPRISE:
        max_projects = 10
        voice_minutes = 500
        voice_enabled = True
        integrations = True
    else:
        max_projects = 3  # Plan Core incluye de 1 a 3 proyectos
        voice_minutes = 0
        voice_enabled = False
        integrations = False

    # 2. Crear el Tenant
    new_company = Company(
        name=data.name,
        license_start=datetime.utcnow(),
        license_end=datetime.utcnow() + timedelta(days=365), # 1 año de vigencia
        plan_tier=data.plan_tier,
        max_projects_allowed=max_projects,
        has_voice_agents=voice_enabled,
        has_enterprise_integrations=integrations,
        voice_minutes_allowance=voice_minutes,
        offline_payment_verified=True,
        is_active=True
    )
    db.add(new_company)
    db.flush() # Obtener ID auto-generado antes del commit

    # 3. Crear el Administrador del Cliente asociado a este Tenant
    company_admin = User(
        company_id=new_company.id,
        email=data.admin_email,
        hashed_password=get_password_hash(data.admin_password),
        role=UserRole.ADMIN,
        is_active=True
    )
    db.add(company_admin)
    db.commit()

    return {
        "status": "success",
        "company_id": new_company.id,
        "provisioned_plan": data.plan_tier.value,
        "max_projects": max_projects
    }