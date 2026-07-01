from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

# Importamos managers, modelos y esquemas relacionales/documentales
from app.models.mongo_models import db_manager, ChatMessage as MongoChatMessage
from app.models.pg_models import get_db, User, UserRole, Lead, ChatMessage as PgChatMessage, FunnelStage
from app.api.deps import RoleChecker
from app.services.ai_service import AIService

router = APIRouter()

# =================================================================
# ESQUEMAS DE ENTRADA / SALIDA (VALIDACIÓN)
# =================================================================
class ConversationCreatePayload(BaseModel):
    lead_id: str
    agent_type: str  # ej. 'leasing', 'investor', 'financing'
    messages: List[MongoChatMessage]
    total_tokens_used: int = 0

class InteractiveChatRequest(BaseModel):
    lead_id: str
    message: str

class InteractiveChatResponse(BaseModel):
    status: str
    response: str

# =================================================================
# ENDPOINT INTERACTIVO: CHAT EN TIEMPO REAL CON IA (OPENROUTER/DEEPSEEK)
# =================================================================
@router.post("/chat", response_model=InteractiveChatResponse, summary="Interactuar con el Copilot de IA en tiempo real")
async def interact_with_ai_copilot(payload: InteractiveChatRequest, db: Session = Depends(get_db)):
    """
    Endpoint omnicanal interactivo. Recibe un mensaje, analiza el contexto histórico 
    del lead en Postgres, genera la respuesta con DeepSeek vía OpenRouter y persiste el hilo.
    """
    # 1. Validamos la existencia del Lead en PostgreSQL
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="El Lead especificado no existe en los registros.")
        
    # 2. Extraemos el historial cronológico de mensajes de este lead
    history_records = db.query(PgChatMessage).filter(
        PgChatMessage.lead_id == payload.lead_id
    ).order_by(PgChatMessage.created_at.asc()).all()
    
    # 3. Construimos el hilo de mensajes para OpenRouter
    formatted_messages = []
    
    # Inyectamos el Prompt de Sistema Maestro para guiar la personalidad de la IA
    formatted_messages.append({
        "role": "system",
        "content": (
            "You are Black Penguin Sales Copilot, an elite virtual advisor specialized in high-end real estate investments in Miami and top US markets. "
            "Your objective is to nurture, qualify, and drive the lead to schedule a meeting with a human broker. "
            "Be extremely professional, concise, and smart. Answer in the same language the investor uses."
        )
    })
    
    # Inyectamos los mensajes anteriores recuperados de Postgres
    for msg in history_records:
        formatted_messages.append({"role": msg.role, "content": msg.content})
        
    # Añadimos el nuevo mensaje que acaba de enviar el prospecto
    formatted_messages.append({"role": "user", "content": payload.message})
    
    # 4. Consumimos asíncronamente el servicio de OpenRouter (DeepSeek)
    ai_reply = await AIService.generate_response(formatted_messages)
    
    # 5. Guardamos de forma inmediata ambos mensajes en PostgreSQL para mantener la memoria viva
    user_msg_db = PgChatMessage(lead_id=payload.lead_id, role="user", content=payload.message)
    ai_msg_db = PgChatMessage(lead_id=payload.lead_id, role="assistant", content=ai_reply)
    
    # Si el lead estaba en etapa 'NEW', al interactuar con la IA avanza automáticamente a 'CONTACTED'
    if lead.funnel_stage == FunnelStage.NEW:
        lead.funnel_stage = FunnelStage.CONTACTED
        
    db.add(user_msg_db)
    db.add(ai_msg_db)
    db.commit()
    
    return InteractiveChatResponse(status="success", response=ai_reply)


# =================================================================
# ENDPOINT RESPALDO: GUARDAR HISTORIAL DOCUMENTAL (MONGODB)
# =================================================================
@router.post("/", status_code=status.HTTP_201_CREATED, summary="Guardar Historial Completo de Conversación en NoSQL")
async def save_conversation_log(
    payload: ConversationCreatePayload,
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.SALES, UserRole.MKT]))
):
    """
    Recibe la transcripción masiva de un chat o llamada y la inserta en MongoDB 
    de forma asíncrona bajo el aislamiento perimetral estricto de la empresa (Tenant).
    """
    if not db_manager.db:
        raise HTTPException(
            status_code=503, 
            detail="El motor de persistencia documental MongoDB no se encuentra en línea."
        )

    # Construimos el documento final inyectando el company_id del contexto autenticado del usuario
    document = {
        "_id": str(uuid.uuid4()),  
        "lead_id": payload.lead_id,
        "company_id": current_user.company_id, # <-- Aislamiento Perimetral SaaS
        "agent_type": payload.agent_type,
        "messages": [msg.model_dump() for msg in payload.messages],
        "total_tokens_used": payload.total_tokens_used,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Insertamos de manera asíncrona usando Motor
    await db_manager.db["conversations"].insert_one(document)
    
    return {"status": "success", "message": "Historial de conversación respaldado en MongoDB de forma aislada."}