from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.properties.models import Project
from app.modules.properties.schemas import ProjectCreate, ProjectResponse
from app.modules.tenants.models import Company
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

router = APIRouter()

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    """Crea un nuevo proyecto inmobiliario respetando los límites del plan (SaaS)."""
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    current_projects_count = db.query(Project).filter(Project.company_id == current_user.company_id).count()
    
    if current_projects_count >= company.max_projects_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Límite de proyectos alcanzado. Tu plan permite un máximo de {company.max_projects_allowed} proyectos."
        )

    new_project = Project(
        **project_in.model_dump(),
        company_id=current_user.company_id,
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
    """Obtiene la lista de proyectos inmobiliarios aislada para el tenant."""
    return db.query(Project).filter(Project.company_id == current_user.company_id).all()