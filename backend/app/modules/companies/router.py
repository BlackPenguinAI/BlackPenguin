from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.core.security import get_password_hash

from .models import Company
from .schemas import CompanyResponse
from . import services
from app.modules.subscriptions.models import SubscriptionPlan

router = APIRouter()

@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company_workspace(
    name: str = Form(...),
    plan_id: str = Form(...),
    duration_months: int = Form(...),
    admin_first_name: str = Form(...),
    admin_last_name_paternal: str = Form(...),
    admin_last_name_maternal: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    receipt_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Crea una Compañía y su primer Administrador simultáneamente."""
    
    if db.query(User).filter(User.email == admin_email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado.")
        
    if not db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first():
        raise HTTPException(status_code=400, detail="Plan de suscripción no válido.")

    # 1. Guardar recibo
    receipt_url = services.save_receipt_file(admin_email, receipt_file) if receipt_file else None

    # 2. Crear Compañía
    start_date = datetime.utcnow()
    new_company = Company(
        name=name, plan_id=plan_id, 
        license_start=start_date, license_end=start_date + relativedelta(months=duration_months),
        payment_receipt_url=receipt_url, is_active=True
    )
    db.add(new_company)
    db.commit()
    db.refresh(new_company)

    # 3. Crear Admin
    new_admin = User(
        email=admin_email, hashed_password=get_password_hash(admin_password),
        full_name=admin_first_name, last_name_paternal=admin_last_name_paternal,
        last_name_maternal=admin_last_name_maternal, role=UserRole.ADMIN,
        company_id=new_company.id, is_active=True
    )
    db.add(new_admin)
    db.commit()
    
    return new_company

@router.get("/", response_model=List[CompanyResponse])
def get_companies(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return db.query(Company).options(joinedload(Company.plan)).order_by(Company.created_at.desc()).all()