from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from app.modules.ai_core.services import get_ai_config
from app.integrations.openrouter_client import generate_llm_response

from .models import SenderType, OnboardingMessage
from .schemas import CompanyProfileResponse, ChatMessagePayload, ChatMessageResponse, ScrapeRequest
from . import services
from .scraper import scrape_and_enrich_profile

router = APIRouter()

@router.get("/profile", response_model=CompanyProfileResponse, summary="Obtener perfil de la compañía")
def get_company_profile(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    return services.get_or_create_profile(db, current_user.company_id)

@router.get("/chat", response_model=List[ChatMessageResponse], summary="Obtener historial del chat")
def get_chat_history(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))):
    session = services.get_or_create_session(db, current_user.company_id)
    messages = db.query(OnboardingMessage).filter(OnboardingMessage.session_id == session.id).order_by(OnboardingMessage.created_at.asc()).all()
    
    return [
        {"sender": "user" if m.sender == SenderType.USER else "ai", "content": m.content, "created_at": m.created_at} 
        for m in messages
    ]

@router.post("/chat", response_model=ChatMessageResponse, summary="Enviar mensaje a la IA")
async def send_chat_message(
    payload: ChatMessagePayload, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.ADMIN, UserRole.MKT]))
):
    session = services.get_or_create_session(db, current_user.company_id)
    profile = services.get_or_create_profile(db, current_user.company_id)
    ai_config = get_ai_config(db, current_user.company_id)
    
    if not ai_config.openrouter_api_key:
        raise HTTPException(status_code=500, detail="Configuración de IA incompleta.")

    # 1. Guardar mensaje del usuario
    services.save_message(db, session.id, SenderType.USER, payload.message)

    # 2. Armar contexto para la IA
    agent_config = ai_config.agent_onboarding_empresa
    system_instruction = f"{agent_config.get('system_prompt', '')}\n\nProtocolo:\n{agent_config.get('protocol_prompt', '')}\n\nRestricciones:\n{agent_config.get('guardrails_prompt', '')}"
    
    messages_history = [{"role": "system", "content": system_instruction}]
    history = db.query(OnboardingMessage).filter(OnboardingMessage.session_id == session.id).order_by(OnboardingMessage.created_at.asc()).all()
    for msg in history[-10:]: # Mandamos los últimos 10
        messages_history.append({"role": "user" if msg.sender == SenderType.USER else "assistant", "content": msg.content})

    # 3. Llamar a OpenRouter
    model = agent_config.get("model", "openai/gpt-4o-mini")
    ai_response_text = await generate_llm_response(ai_config.openrouter_api_key, model, messages_history)

    # 4. Guardar respuesta IA
    ai_msg = services.save_message(db, session.id, SenderType.AI, ai_response_text)

    return {"sender": "ai", "content": ai_msg.content, "created_at": ai_msg.created_at}

@router.post("/scrape-website", summary="Lanza web scraping en background")
def trigger_scrape(
    payload: ScrapeRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(RoleChecker([UserRole.ADMIN]))
):
    background_tasks.add_task(scrape_and_enrich_profile, current_user.company_id, str(payload.url))
    return {"message": "El escaneo profundo ha comenzado en segundo plano."}