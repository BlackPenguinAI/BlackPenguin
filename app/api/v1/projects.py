from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import uuid

# Importamos la base de datos y los modelos físicos
from app.models.pg_models import get_db, Project, User, UserRole, Company
# Importamos las dependencias de seguridad
from app.api.deps import get_current_user, RoleChecker

router = APIRouter()

# ==========================================
# ESQUEMAS PYDANTIC (Validación de datos)
# ==========================================
class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None

class ProjectResponse(ProjectCreate):
    id: uuid.UUID
    company_id: uuid.UUID
    is_active: bool

    class Config:
        from_attributes = True

# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    """
    Crea un nuevo proyecto inmobiliario.
    Solo accesible para Administradores o equipo de Marketing de la empresa.
    """
    # 1. Validar límites del plan (Opcional pero recomendado según tu arquitectura)
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    current_projects_count = db.query(Project).filter(Project.company_id == current_user.company_id).count()
    
    if current_projects_count >= company.max_projects_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de proyectos alcanzado. Tu plan permite un máximo de {company.max_projects_allowed} proyectos."
        )

    # 2. Crear el proyecto inyectando automáticamente el company_id del usuario
    new_project = Project(
        name=project_in.name,
        description=project_in.description,
        address=project_in.address,
        city=project_in.city,
        country=project_in.country,
        company_id=current_user.company_id,  # <- ¡MAGIA MULTI-TENANT AQUÍ!
        is_active=True
    )
    
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    
    return new_project

@router.get("/", response_model=List[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))
):
    """
    Obtiene la lista de proyectos inmobiliarios.
    Aislado automáticamente para mostrar solo los de la empresa del usuario.
    """
    # El filtrado por company_id garantiza que nadie vea datos de otros clientes
    projects = db.query(Project).filter(Project.company_id == current_user.company_id).all()
    return projects