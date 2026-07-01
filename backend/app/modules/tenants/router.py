from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.db.postgres import get_db
from app.core.security import get_password_hash

from app.modules.tenants.models import Company, PlanTier
from app.modules.tenants.schemas import ProvisionCompanyRequest
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker 

router = APIRouter()

@router.post("/companies/", dependencies=[Depends(RoleChecker([UserRole.SUPERADMIN]))], status_code=201)
def provision_new_tenant(data: ProvisionCompanyRequest, db: Session = Depends(get_db)):
    """Crea una nueva empresa/inquilino y su usuario administrador inicial."""
    # Reglas lógicas del Plan
    if data.plan_tier == PlanTier.ENTERPRISE:
        max_projects, voice_minutes, voice_enabled, integrations = 10, 500, True, True
    else:
        max_projects, voice_minutes, voice_enabled, integrations = 3, 0, False, False

    # Crear Tenant
    new_company = Company(
        name=data.name,
        license_end=datetime.utcnow() + timedelta(days=365),
        plan_tier=data.plan_tier,
        max_projects_allowed=max_projects,
        has_voice_agents=voice_enabled,
        has_enterprise_integrations=integrations,
        voice_minutes_allowance=voice_minutes,
        offline_payment_verified=True
    )
    db.add(new_company)
    db.flush() # Obtenemos el ID auto-generado antes del commit

    # Crear Admin de la Empresa
    company_admin = User(
        company_id=new_company.id,
        email=data.admin_email,
        hashed_password=get_password_hash(data.admin_password),
        role=UserRole.ADMIN
    )
    db.add(company_admin)
    db.commit()

    return {"status": "success", "message": f"Tenant '{data.name}' provisionado exitosamente."}