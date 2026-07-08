from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
import uuid
from datetime import datetime
from app.db.postgres import Base
from pydantic import BaseModel, Field
from typing import Optional

# =========================================================
# 🚀 TABLA MAESTRA: Inteligencia Distribuida (Multi-Agentes)
# =========================================================
class AIConfiguration(Base):
    __tablename__ = "ai_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    
    openrouter_api_key = Column(String(255), nullable=True)
    
    # 🚀 CERO DATA SINTÉTICA: Lista vacía por defecto
    available_models = Column(JSON, default=list)
    
    # 🚀 AGENTES EN BLANCO: Sin modelos preasignados
    agent_onboarding_empresa = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_onboarding_proyectos = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_ventas = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_reporteria = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# =========================================================
# 1. Modelo Relacional (Postgres) - Memoria Viva
# =========================================================
class PgChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# =========================================================
# 2. Modelos Documentales (MongoDB) - Transcripciones
# =========================================================
class MessageMetadata(BaseModel):
    model_version: Optional[str] = Field(None)
    intent_detected: Optional[str] = Field(None)
    tokens_used: Optional[int] = Field(None)

class MongoChatMessage(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[MessageMetadata] = Field(default=None)