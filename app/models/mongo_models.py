from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime
from bson import ObjectId

# ==========================================
# CONFIGURACIÓN BASE PARA MONGODB (BSON)
# ==========================================
class MongoBaseModel(BaseModel):
    """Configuración global para mapear los ObjectIds nativos de Mongo a strings en FastAPI"""
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str, datetime: lambda dt: dt.isoformat()}
    )

# ==========================================
# 1. MODELOS DE HISTORIAL CONVERSACIONAL (V2.0 MULTICANAL)
# ==========================================

class MessageMetadata(BaseModel):
    """Metadatos expandidos para soportar el Billing de Enterprise y analítica"""
    model_version: Optional[str] = Field(None, description="Ej: gpt-4o, deepseek-chat")
    intent_detected: Optional[str] = Field(None, description="Intención detectada por el LLM")
    
    # --- Nuevos campos de Facturación v2.0 ---
    tokens_used: Optional[int] = Field(None, description="Tokens consumidos en esta interacción")
    voice_minutes_used: Optional[int] = Field(None, description="Minutos a descontar de la bolsa mensual")
    audio_recording_url: Optional[str] = Field(None, description="Ruta en DO Spaces del MP3 de la llamada")

class ChatMessage(BaseModel):
    sender: str = Field(..., description="'user' o 'ai_agent'")
    agent_type: Optional[str] = Field(
        default="base_advisor", 
        description="'base_advisor', 'leasing_ai', 'investor_ai', 'financing_ai'"
    )
    content: str = Field(..., description="Texto del mensaje o transcripción de la llamada")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[MessageMetadata] = Field(default_factory=MessageMetadata)

class Conversation(MongoBaseModel):
    id: Optional[ObjectId] = Field(alias="_id", default=None)
    company_id: str
    lead_id: str
    channel: str = Field(..., description="'whatsapp', 'meta_ads', 'web_chat', 'voice_call'")
    status: str = Field(default="active", description="'active', 'paused', 'archived'")
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# ==========================================
# 2. MODELOS DE AUDITORÍA (SEGURIDAD Y EVENTOS COMERCIALES)
# ==========================================

class AuditLog(MongoBaseModel):
    id: Optional[ObjectId] = Field(alias="_id", default=None)
    company_id: Optional[str] = None # Null para acciones de Superadmin
    user_id: str = Field(..., description="UUID del usuario o 'SYSTEM' si es automático")
    
    # Eventos ampliados v2.0
    action_type: str = Field(
        ..., 
        description="LOGIN, EXPORT_LEADS, UPGRADE_PLAN, ADDON_PURCHASED, VOICE_MINUTES_EXCEEDED"
    )
    resource: str = Field(..., description="Entidad afectada (ej: 'companies', 'leads')")
    ip_address: str
    
    details: Dict[str, Any] = Field(
        default_factory=dict, 
        description="JSON dinámico. Ej: {'agent_type': 'financing', 'cost': 500}"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# ==========================================
# 3. MODELOS DE CUMPLIMIENTO LEGAL (COMPLIANCE)
# ==========================================

class ComplianceLog(MongoBaseModel):
    id: Optional[ObjectId] = Field(alias="_id", default=None)
    company_id: str
    lead_id: str
    event_type: str = Field(..., description="'OPT_IN', 'OPT_OUT', 'T&C_ACCEPTED'")
    channel: str = Field(..., description="'whatsapp', 'voice_call' (Detectado por reconocimiento de voz)")
    document_version: Optional[str] = None
    ip_address: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)