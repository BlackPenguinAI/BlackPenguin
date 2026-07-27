from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.db.postgres import get_db
from app.modules.properties.models import Project, ProjectProfile, ProjectSession, ProjectMessage
from app.modules.properties.schemas import ProjectCreate, ProjectResponse, ChatMessagePayload, ChatMessageResponse
from app.modules.tenants.models import Company, SenderType
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker

router = APIRouter()

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    """Crea un nuevo proyecto y le asigna su Perfil y Chat de Onboarding."""
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    current_projects_count = db.query(Project).filter(Project.company_id == current_user.company_id).count()
    
    if company.plan and current_projects_count >= company.plan.max_projects:
        raise HTTPException(status_code=400, detail=f"Límite de proyectos alcanzado para su plan.")

    # 1. Crear el Proyecto
    new_project = Project(**project_in.model_dump(), company_id=current_user.company_id, is_active=True)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # 2. Crear su Perfil en blanco (3 Pilares)
    new_profile = ProjectProfile(project_id=new_project.id)
    db.add(new_profile)
    
    # 3. Crear su Sesión de Chat
    new_session = ProjectSession(project_id=new_project.id)
    db.add(new_session)
    db.commit()
    
    # 4. Inyectar el Prompt de Bienvenida (El paso 1 de tu protocolo)
    welcome_msg = ProjectMessage(
        session_id=new_session.id,
        sender=SenderType.AI,
        content=f"Hello! I am Black Penguin's AI Data Architect. Let's set up the data for **{new_project.name}**. To get started, please provide the exact location of the project and upload any brochures or pricing tables you have."
    )
    db.add(welcome_msg)
    db.commit()

    return new_project

@router.get("/", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    """Lista los proyectos con su estatus de perfil (Eager Loading)"""
    return db.query(Project).options(joinedload(Project.profile)).filter(Project.company_id == current_user.company_id).all()

@router.get("/{project_id}/chat", response_model=List[ChatMessageResponse])
def get_project_chat_history(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    """Obtiene el historial del chat para este proyecto en particular"""
    session = db.query(ProjectSession).filter(ProjectSession.project_id == project_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sesión de chat no encontrada.")
        
    history = db.query(ProjectMessage).filter(ProjectMessage.session_id == session.id).order_by(ProjectMessage.created_at.asc()).all()
    return [{"sender": "user" if m.sender == SenderType.USER else "ai", "content": m.content} for m in history]

# NOTA PARA TI: En el futuro conectaremos este endpoint con tu motor LLM (OpenRouter) usando tus 3 Prompts Maestros.
@router.post("/{project_id}/chat")
def send_project_chat_message(project_id: str, payload: ChatMessagePayload, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    # Aquí irá la lógica de extracción de datos con IA que programaremos en el siguiente paso.
    pass