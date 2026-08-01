from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.ai_core.services import get_ai_config
from app.integrations.openrouter_client import generate_llm_response

from .models import Project, ProjectSession, ProjectMessage, SenderType
from .schemas import ProjectCreate, ProjectResponse, ChatMessagePayload, ChatMessageResponse
from . import services

router = APIRouter()

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    services.check_project_limits(db, current_user.company_id)

    new_project = Project(**payload.model_dump(), company_id=current_user.company_id, is_active=True)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)

    # Inicializar el Data Extractor
    _, session = services.setup_project_onboarding(db, new_project.id)
    
    welcome_msg = f"Hello! I am Black Penguin's AI Data Architect. Let's set up the data for **{new_project.name}**. To get started, please provide the exact location of the project and upload any brochures or pricing tables."
    services.save_message(db, session.id, SenderType.AI, welcome_msg)

    return new_project

@router.get("/", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT, UserRole.SALES]))):
    return db.query(Project).options(joinedload(Project.profile)).filter(Project.company_id == current_user.company_id).all()

@router.get("/{project_id}/chat", response_model=List[ChatMessageResponse])
def get_project_chat(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    session = db.query(ProjectSession).filter(ProjectSession.project_id == project_id).first()
    if not session: raise HTTPException(status_code=404, detail="Sesión no encontrada.")
        
    messages = db.query(ProjectMessage).filter(ProjectMessage.session_id == session.id).order_by(ProjectMessage.created_at.asc()).all()
    return [{"sender": "user" if m.sender == SenderType.USER else "ai", "content": m.content, "created_at": m.created_at} for m in messages]

@router.post("/{project_id}/chat", response_model=ChatMessageResponse)
async def send_project_chat(
    project_id: str, 
    payload: ChatMessagePayload, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    session = db.query(ProjectSession).filter(ProjectSession.project_id == project_id).first()
    ai_config = get_ai_config(db, current_user.company_id)
    
    services.save_message(db, session.id, SenderType.USER, payload.message)

    agent_config = ai_config.agent_onboarding_proyectos
    system_instruction = f"{agent_config.get('system_prompt', '')}\n\nProtocolo:\n{agent_config.get('protocol_prompt', '')}\n\nRestricciones:\n{agent_config.get('guardrails_prompt', '')}"
    
    messages_history = [{"role": "system", "content": system_instruction}]
    history = db.query(ProjectMessage).filter(ProjectMessage.session_id == session.id).order_by(ProjectMessage.created_at.asc()).all()
    for msg in history[-10:]:
        messages_history.append({"role": "user" if msg.sender == SenderType.USER else "assistant", "content": msg.content})

    model = agent_config.get("model", "openai/gpt-4o-mini")
    ai_response_text = await generate_llm_response(ai_config.openrouter_api_key, model, messages_history)

    ai_msg = services.save_message(db, session.id, SenderType.AI, ai_response_text)
    
    # NOTA: Aquí podemos agregar el "Scraper Silencioso" como Background Task para actualizar el ProjectProfile 
    # de la misma forma que lo hicimos en company_onboarding.

    return {"sender": "ai", "content": ai_msg.content, "created_at": ai_msg.created_at}