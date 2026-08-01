from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import Project, ProjectProfile, ProjectSession, ProjectMessage, SenderType
from app.modules.companies.models import Company

def check_project_limits(db: Session, company_id: str):
    """Verifica si la empresa puede crear más proyectos según su plan."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.plan:
        raise HTTPException(status_code=400, detail="La compañía no tiene un plan asignado.")
        
    current_count = db.query(Project).filter(Project.company_id == company_id).count()
    if current_count >= company.plan.max_projects:
        raise HTTPException(status_code=400, detail=f"Límite alcanzado. Tu plan permite {company.plan.max_projects} proyectos.")

def setup_project_onboarding(db: Session, project_id: str):
    """Crea el perfil en blanco y la sesión de chat para un nuevo proyecto."""
    profile = ProjectProfile(project_id=project_id)
    session = ProjectSession(project_id=project_id)
    db.add(profile)
    db.add(session)
    db.commit()
    db.refresh(session)
    return profile, session

def save_message(db: Session, session_id: str, sender: SenderType, content: str):
    msg = ProjectMessage(session_id=session_id, sender=sender, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg