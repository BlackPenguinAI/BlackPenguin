from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.tenants.models import Company
from app.modules.properties.models import Project # 🚀 IMPORTACIÓN CORREGIDA: Ahora apunta a tu módulo properties
from app.modules.tenants.schemas import CompanyCreate, CompanyUpdate, CompanyResponse
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker
from app.modules.sales.models import WaitlistEmail 

router = APIRouter()

# =========================================================
# 📊 DASHBOARD: ESTADÍSTICAS GLOBALES
# =========================================================
@router.get("/stats", summary="Estadísticas globales para el Dashboard")
def get_global_stats(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    """Devuelve el conteo maestro de la plataforma para el Superadmin."""
    return {
        "total_companies": db.query(Company).count(),
        "active_companies": db.query(Company).filter(Company.is_active == True).count(),
        "total_projects": db.query(Project).count(),
        "total_waitlist": db.query(WaitlistEmail).count(),
        "total_users": db.query(User).count(),
        "system_status": "Operational"
    }

# =========================================================
# 🏢 CRUD DE EMPRESAS (TENANTS)
# =========================================================
@router.get("/", response_model=List[CompanyResponse], summary="Listar Empresas (Developers)")
def get_companies(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    return db.query(Company).order_by(Company.license_start.desc()).all()

@router.post("/", response_model=CompanyResponse, summary="Crear Nueva Empresa")
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    new_company = Company(**payload.model_dump())
    db.add(new_company)
    db.commit()
    db.refresh(new_company)
    return new_company

@router.put("/{company_id}", response_model=CompanyResponse, summary="Actualizar Empresa")
def update_company(company_id: str, payload: CompanyUpdate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(company, key, value)
        
    db.commit()
    db.refresh(company)
    return company

@router.delete("/{company_id}", summary="Eliminar Empresa")
def delete_company(company_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN]))):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
    db.delete(company)
    db.commit()
    return {"message": "Empresa eliminada con éxito"}