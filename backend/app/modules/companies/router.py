from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.users import services as user_services

from .models import Company
from .schemas import CompanyResponse
from . import services
from app.modules.subscriptions.models import SubscriptionPlan

router = APIRouter()

# ==========================================
# 1. CREAR EMPRESA Y ADMIN
# ==========================================
@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company_workspace(
    name: str = Form(...),
    plan_id: str = Form(...),
    duration_months: int = Form(...),
    admin_first_name: str = Form(...),
    admin_last_name: str = Form(...),
    admin_email: str = Form(...),
    is_active: str = Form('true'),       # 🚀 Company Status (default 'true')
    admin_is_active: str = Form('true'), # 🚀 User Status (default 'true')
    start_date: Optional[str] = Form(None),
    receipt_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Crea una Compañía y su Administrador con sus respectivos estados."""
    
    if db.query(User).filter(User.email == admin_email).first():
        raise HTTPException(status_code=400, detail="The email is already registered.")
        
    if not db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first():
        raise HTTPException(status_code=400, detail="Invalid subscription plan.")

    receipt_url = services.save_receipt_file(admin_email, receipt_file) if receipt_file else None

    parsed_start_date = datetime.utcnow()
    if start_date:
        try:
            parsed_start_date = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            pass

    is_active_bool = str(is_active).lower() == 'true'
    admin_is_active_bool = str(admin_is_active).lower() == 'true'

    # Crear Compañía con su estado seleccionado
    new_company = Company(
        name=name, plan_id=plan_id, 
        license_start=parsed_start_date, 
        license_end=parsed_start_date + relativedelta(months=duration_months),
        payment_receipt_url=receipt_url, 
        is_active=is_active_bool
    )
    db.add(new_company)
    db.flush()

    try:
        new_admin = user_services.invite_company_administrator(
            db,
            company_id=new_company.id,
            email=admin_email,
            first_name=admin_first_name,
            last_name=admin_last_name,
            is_active=admin_is_active_bool,
            invited_by_user_id=current_user.id,
        )
        db.refresh(new_company)
    except Exception:
        db.rollback()
        raise

    return new_company

# ==========================================
# 2. LISTAR EMPRESAS
# ==========================================
@router.get("/", response_model=List[CompanyResponse])
def get_companies(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return db.query(Company).options(
        joinedload(Company.plan),
        joinedload(Company.users)
    ).order_by(Company.created_at.desc()).all()

# ==========================================
# 3. ACTUALIZAR EMPRESA Y ADMIN (EDIT)
# ==========================================
@router.put("/{company_id}/", response_model=CompanyResponse)
def update_company(
    company_id: str,
    name: str = Form(...),
    plan_id: str = Form(...),
    duration_months: int = Form(...),
    admin_first_name: str = Form(...),
    admin_last_name: str = Form(...),
    admin_email: str = Form(...),
    is_active: str = Form('true'),       
    admin_is_active: str = Form('true'), 
    start_date: Optional[str] = Form(None),
    receipt_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    company = db.query(Company).options(
        joinedload(Company.plan), 
        joinedload(Company.users)
    ).filter(Company.id == company_id).first()
    
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    is_active_bool = str(is_active).lower() == 'true'
    admin_is_active_bool = str(admin_is_active).lower() == 'true'

    company.name = name
    company.plan_id = plan_id
    company.is_active = is_active_bool

    if receipt_file:
        company.payment_receipt_url = services.save_receipt_file(admin_email, receipt_file)

    if start_date:
        try:
            company.license_start = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            pass
    if company.license_start:
        company.license_end = company.license_start + relativedelta(months=duration_months)

    admin_user = db.query(User).filter(User.company_id == company_id, User.role == UserRole.ADMIN).first()
    if admin_user:
        if admin_user.email != admin_email.strip().casefold():
            raise HTTPException(
                status_code=422,
                detail="Administrator email cannot be changed here. Invite a replacement through a verified identity workflow.",
            )
        
        admin_user.first_name = admin_first_name
        admin_user.last_name = admin_last_name
        if admin_user.is_active != admin_is_active_bool:
            user_services.set_user_enabled(db, user=admin_user, enabled=admin_is_active_bool)

    db.commit()
    db.refresh(company)
    return company

# ==========================================
# 4. ELIMINAR EMPRESA
# ==========================================
@router.delete("/{company_id}/", status_code=status.HTTP_200_OK)
def delete_company(
    company_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    
    db.delete(company)
    db.commit()
    return {"detail": "Company deleted successfully"}

# ==========================================
# 5. REENVIAR ACTIVACIÓN
# ==========================================
@router.post("/{company_id}/resend-activation/", status_code=status.HTTP_200_OK)
def resend_activation(
    company_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    
    admin_user = db.query(User).filter(
        User.company_id == company_id, User.role == UserRole.ADMIN,
    ).first()
    if not admin_user:
        raise HTTPException(status_code=404, detail="Company administrator not found.")
    user_services.resend_user_activation(db, user=admin_user, invited_by_user_id=current_user.id)
    return {"detail": "Activation link sent"}
