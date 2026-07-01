from fastapi import APIRouter, UploadFile, Depends, HTTPException, status, File, Form
from sqlalchemy.orm import Session
import uuid
from datetime import datetime
import os
import io
import pypdf
from openai import AsyncOpenAI

from pydantic import BaseModel # 🚀 IMPORTANTE
from typing import List, Dict  # 🚀 IMPORTANTE

from app.db.postgres import get_db
from app.db.mongo import db_manager
from app.modules.auth.models import User, UserRole
from app.modules.auth.deps import RoleChecker
from app.modules.sales.models import Lead, FunnelStage
from app.modules.ai.models import PgChatMessage
from app.modules.ai.schemas import InteractiveChatRequest, InteractiveChatResponse, ConversationCreatePayload
from app.modules.ai.ai_service import AIService

router = APIRouter()

# ==========================================
# RUTAS ORIGINALES DEL PROYECTO
# ==========================================

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

# ==========================================
# NUEVA RUTA: LECTOR DE PDF CON OPENROUTER
# ==========================================

#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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# 1. Esquema para recibir el historial de chat de Angular
class ChatMessagePayload(BaseModel):
    messages: List[Dict[str, str]]

# 2. Endpoint para procesar el PDF inicial
@router.post("/analyze-pdf")
async def analyze_pdf(
    file: UploadFile = File(...),
    prompt: str = Form("Extrae la información.")
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF válido.")

    try:
        pdf_bytes = await file.read()
        pdf_reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        
        extracted_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"

        # 🚀 PROMPT BLINDADO: Le exigimos estructura y preguntar por confirmación
        system_prompt = (
            "Eres el Copiloto Comercial de Black Penguin. "
            "El sistema interno ya extrajo el texto de un documento PDF por ti. "
            "TU ÚNICA TAREA ES: Extraer los datos comerciales (ubicación, amenidades, tipologías), "
            "presentarlos de forma altamente estructurada usando viñetas y emojis, y AL FINALIZAR, "
            "DEBES PREGUNTAR EXPLÍCITAMENTE al usuario si toda la información es correcta o si hay algún dato que desee corregir o actualizar. "
            "REGLA DE ORO: No menciones al PDF, ni digas 'Aquí tienes la información', solo devuelve la data estructurada directamente.\n\n"
            f"--- INICIO DE LOS DATOS ---\n{extracted_text[:30000]}\n--- FIN DE LOS DATOS ---"
        )
        
        response = await client.chat.completions.create(
            #openai/gpt-4o-mini
            model="openrouter/free",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Por favor procesa los datos y dime qué encontraste."}
            ]
        )

        return {
            "message": response.choices[0].message.content,
            "filename": file.filename
        }
    except Exception as e:
        print(f"Error procesando PDF: {str(e)}")
        raise HTTPException(status_code=500, detail="Error en IA.")

# 3. Endpoint para conversar después de subir el PDF (Follow-ups)
@router.post("/chat-message")
async def chat_message(payload: ChatMessagePayload):
    try:
        # Le damos contexto de que está ayudando a corregir los datos
        system_msg = {
            "role": "system", 
            "content": "Eres el Copiloto Comercial de Black Penguin. Estás conversando con el usuario para afinar, corregir o actualizar la información comercial de su proyecto. Sé directo, proactivo y amable."
        }
        
        messages_for_ai = [system_msg] + payload.messages
        
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages_for_ai
        )
        return {"message": response.choices[0].message.content}
    except Exception as e:
        print(f"Error en chat fluido: {e}")
        raise HTTPException(status_code=500, detail="Error de conexión con IA.")