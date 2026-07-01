from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid
from datetime import datetime

from app.db.postgres import get_db
from app.db.mongo import db_manager
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker
from app.modules.sales.models import Lead, FunnelStage
from app.modules.ai.models import PgChatMessage
from app.modules.ai.schemas import InteractiveChatRequest, InteractiveChatResponse, ConversationCreatePayload
from app.modules.ai.ai_service import AIService

router = APIRouter()

@router.post("/chat", response_model=InteractiveChatResponse, summary="Chat en tiempo real")
async def interact_with_ai_copilot(payload: InteractiveChatRequest, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado.")
        
    history = db.query(PgChatMessage).filter(PgChatMessage.lead_id == payload.lead_id).order_by(PgChatMessage.created_at.asc()).all()
    
    formatted_messages = [{"role": "system", "content": "You are Black Penguin Sales Copilot, an elite real estate advisor..."}]
    for msg in history:
        formatted_messages.append({"role": msg.role, "content": msg.content})
    formatted_messages.append({"role": "user", "content": payload.message})
    
    ai_reply = await AIService.generate_response(formatted_messages)
    
    db.add(PgChatMessage(lead_id=payload.lead_id, role="user", content=payload.message))
    db.add(PgChatMessage(lead_id=payload.lead_id, role="assistant", content=ai_reply))
    
    if lead.funnel_stage == FunnelStage.NEW:
        lead.funnel_stage = FunnelStage.CONTACTED
        
    db.commit()
    return InteractiveChatResponse(status="success", response=ai_reply)

@router.post("/log", status_code=status.HTTP_201_CREATED, summary="Guardar log en Mongo")
async def save_conversation_log(
    payload: ConversationCreatePayload,
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.SALES]))
):
    if not db_manager.db:
        raise HTTPException(status_code=503, detail="MongoDB offline.")

    document = {
        "_id": str(uuid.uuid4()),  
        "lead_id": payload.lead_id,
        "company_id": current_user.company_id,
        "agent_type": payload.agent_type,
        "messages": [msg.model_dump() for msg in payload.messages],
        "created_at": datetime.utcnow()
    }
    await db_manager.db["conversations"].insert_one(document)
    return {"status": "success"}