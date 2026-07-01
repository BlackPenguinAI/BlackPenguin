from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime
from bson import ObjectId
from app.core.config import settings

# =================================================================
# GESTOR CENTRAL DE LA CONEXIÓN A MONGODB
# =================================================================
class MongoDBManager:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def connect_to_mongo(self):
        if not self.client:
            print("🚀 Conectando asíncronamente a MongoDB...")
            self.client = AsyncIOMotorClient(settings.MONGO_URL)
            self.db = self.client.get_default_database("blackpenguin_db")
            print("✨ ¡Conexión a MongoDB establecida con éxito!")

    async def close_mongo_connection(self):
        if self.client:
            self.client.close()
            print("🛑 Conexión a MongoDB cerrada limpiamente.")

# 💡 INSTANCIA GLOBAL (Este es el db_manager que busca conversations.py)
db_manager = MongoDBManager()

# Funciones puente para app/main.py
async def connect_to_mongo():
    await db_manager.connect_to_mongo()

async def close_mongo_connection():
    await db_manager.close_mongo_connection()

# ==========================================
# CONFIGURACIÓN BASE PARA MONGODB (BSON)
# ==========================================
class MongoBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str, datetime: lambda dt: dt.isoformat()}
    )

# ==========================================
# MODELOS DE HISTORIAL CONVERSACIONAL
# ==========================================
class MessageMetadata(BaseModel):
    model_version: Optional[str] = Field(None, description="Ej: gpt-4o")
    intent_detected: Optional[str] = Field(None)
    tokens_used: Optional[int] = Field(None)
    voice_minutes_used: Optional[int] = Field(None)
    audio_recording_url: Optional[str] = Field(None)

class ChatMessage(BaseModel):
    sender: str = Field(..., description="'user' o 'ai_agent'")
    agent_type: Optional[str] = Field(default="base_advisor")
    content: str = Field(...)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[MessageMetadata] = Field(default_factory=MessageMetadata)

class Conversation(MongoBaseModel):
    id: Optional[ObjectId] = Field(alias="_id", default=None)
    company_id: str
    lead_id: str
    channel: str = Field(...)
    status: str = Field(default="active")
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)