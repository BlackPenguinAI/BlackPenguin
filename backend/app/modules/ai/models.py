from sqlalchemy import Column, String, Text, DateTime, ForeignKey
import uuid
from datetime import datetime
from app.db.postgres import Base
from pydantic import BaseModel, Field
from typing import Optional

# 1. Modelo Relacional (Postgres) - Memoria Viva
class PgChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# 2. Modelos Documentales (MongoDB) - Transcripciones
class MessageMetadata(BaseModel):
    model_version: Optional[str] = Field(None)
    intent_detected: Optional[str] = Field(None)
    tokens_used: Optional[int] = Field(None)

class MongoChatMessage(BaseModel):
    sender: str = Field(...)
    agent_type: Optional[str] = Field(default="base_advisor")
    content: str = Field(...)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[MessageMetadata] = Field(default_factory=MessageMetadata)