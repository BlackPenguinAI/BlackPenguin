from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
import uuid

# Importamos el manager de Mongo y esquemas
from app.models.mongo_models import db_manager, ChatMessage
from app.models.pg_models import User, UserRole
from app.api.deps import RoleChecker

router = APIRouter()

# ==========================================
# ESQUEMAS DE ENTRADA (VALIDACIÓN)
# ==========================================
class ConversationCreatePayload(BaseModel):
    lead_id: str
    agent_type: str  # ej. 'leasing', 'investor', 'financing'
    messages: List[ChatMessage]
    total_tokens_used: int = 0

# ==========================================
# ENDPOINT DE REGISTRO CONVERSACIONAL
# ==========================================

@router.post("/", status_code=status.HTTP_201_CREATED, summary="Guardar Historial de Conversación de IA")
async def save_conversation_log(
    payload: ConversationCreatePayload,
    # El middleware ya procesó el token. Exigimos que quien guarde sea un rol autorizado (o la propia IA firmando)
    current_user: User = Depends(RoleChecker([UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.SALES, UserRole.MKT]))
):
    """
    Recibe el payload con la transcripción completa del chat/llamada y lo inserta 
    en MongoDB de forma asíncrona, amarrándolo bajo aislamiento estricto de la empresa del usuario.
    """
    if not db_manager.db:
        raise HTTPException(
            status_code=503, 
            detail="El motor de persistencia documental MongoDB no se encuentra en línea."
        )

    # Construimos el documento final inyectando el company_id del contexto autenticado
    document = {
        "_id": str(uuid.uuid4()),  # Generamos un ID único documental
        "lead_id": payload.lead_id,
        "company_id": current_user.company_id, # <-- Aislamiento Perimetral
        "agent_type": payload.agent_type,
        # Convertimos los sub-objetos de Pydantic a diccionarios puros de Python para Mongo
        "messages": [msg.model_dump() for msg in payload.messages],
        "total_tokens_used": payload.total_tokens_used,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    # Insertamos de manera asíncrona usando Motor
    await db_manager.db["conversations"].insert_one(document)

    return {
        "status": "success", 
        "message": "Historial conversacional respaldado en la memoria persistente NoSQL.",
        "conversation_id": document["_id"]
    }