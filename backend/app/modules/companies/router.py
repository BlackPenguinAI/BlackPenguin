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
    admin_password: str = Form(...),
    start_date: Optional[str] = Form(None),
    receipt_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Crea una Compañía y su primer Administrador simultáneamente."""
    
    if db.query(User).filter(User.email == admin_email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado por otro usuario.")
        
    if not db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first():
        raise HTTPException(status_code=400, detail="Plan de suscripción no válido.")

    # Guardar recibo
    receipt_url = services.save_receipt_file(admin_email, receipt_file) if receipt_file else None

    # Procesar fecha de inicio
    parsed_start_date = datetime.utcnow()
    if start_date:
        try:
            parsed_start_date = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            pass

    # Crear Compañía
    new_company = Company(
        name=name, plan_id=plan_id, 
        license_start=parsed_start_date, 
        license_end=parsed_start_date + relativedelta(months=duration_months),
        payment_receipt_url=receipt_url, is_active=True
    )
    db.add(new_company)
    db.commit()
    db.refresh(new_company)

    # Crear Admin
    new_admin = User(
        email=admin_email, hashed_password=get_password_hash(admin_password),
        first_name=admin_first_name, last_name=admin_last_name,
        role=UserRole.ADMIN, company_id=new_company.id, is_active=True
    )
    db.add(new_admin)
    db.commit()

    return new_company

# ==========================================
# 2. LISTAR EMPRESAS
# ==========================================
@router.get("/", response_model=List[CompanyResponse])
def get_companies(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    return db.query(Company).options(joinedload(Company.plan)).order_by(Company.created_at.desc()).all()

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
    is_active: str = Form(...), # FastAPI recibe booleanos de FormData como strings
    start_date: Optional[str] = Form(None),
    admin_password: Optional[str] = Form(None),
    receipt_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Actualiza los datos de la compañía y su administrador principal."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Compañía no encontrada.")

    # Parsear booleano
    is_active_bool = str(is_active).lower() == 'true'

    # Actualizar datos de empresa
    company.name = name
    company.plan_id = plan_id
    company.is_active = is_active_bool

    # Manejar comprobante nuevo (si se sube uno)
    if receipt_file:
        company.payment_receipt_url = services.save_receipt_file(admin_email, receipt_file)

    # Manejar fechas
    if start_date:
        try:
            company.license_start = datetime.strptime(start_date, '%Y-%m-%d')
        except ValueError:
            pass
    company.license_end = company.license_start + relativedelta(months=duration_months)

    # Actualizar usuario Admin
    admin_user = db.query(User).filter(User.company_id == company_id, User.role == UserRole.ADMIN).first()
    if admin_user:
        # Validar colisión de email si lo cambió
        if admin_user.email != admin_email:
            if db.query(User).filter(User.email == admin_email).first():
                raise HTTPException(status_code=400, detail="El correo ya está registrado por otro usuario.")
        
        admin_user.first_name = admin_first_name
        admin_user.last_name = admin_last_name
        admin_user.email = admin_email
        admin_user.is_active = is_active_bool

        if admin_password: # Solo actualiza la contraseña si se ingresó una nueva
            admin_user.hashed_password = get_password_hash(admin_password)

    db.commit()
    db.refresh(company)
    return company

# ==========================================
# 4. ELIMINAR EMPRESA (DELETE)
# ==========================================
@router.delete("/{company_id}/", status_code=status.HTTP_200_OK)
def delete_company(
    company_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))
):
    """Elimina permanentemente una compañía y sus usuarios (Cascade en DB)."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Compañía no encontrada.")
    
    db.delete(company)
    db.commit()
    return {"detail": "Compañía eliminada exitosamente"}

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
        raise HTTPException(status_code=404, detail="Compañía no encontrada.")
    
    # Aquí irá tu lógica de envío de correos (Resend / SMTP)
    return {"detail": "Enlace de activación enviado"}