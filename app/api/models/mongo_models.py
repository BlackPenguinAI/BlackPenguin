from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from app.core.config import settings

# =========================================================
# GESTOR DE CONEXIÓN A MONGODB
# =========================================================
class MongoManager:
    client: AsyncIOMotorClient = None
    db = None

db_manager = MongoManager()

async def connect_to_mongo():
    """Inicializa la conexión a MongoDB usando la URL del entorno."""
    db_manager.client = AsyncIOMotorClient(settings.MONGO_URL)
    # Extraemos el nombre de la base de datos directamente de la URL
    db_name = settings.MONGO_URL.split("/")[-1].split("?")[0]
    db_manager.db = db_manager.client[db_name]
    print(f"✅ Conexión asíncrona a MongoDB establecida: {db_name}")

async def close_mongo_connection():
    """Cierra la conexión limpiamente al apagar el servidor."""
    if db_manager.client:
        db_manager.client.close()
        print("🛑 Conexión a MongoDB cerrada.")

# =========================================================
# MODELOS DE DOCUMENTOS (COLECCIONES NO-SQL)
# =========================================================

class ChatMessage(BaseModel):
    role: str # 'user' o 'assistant'
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ConversationLog(BaseModel):
    """Memoria a largo plazo para los Agentes de IA"""
    lead_id: str
    company_id: str
    agent_type: str # ej. 'leasing', 'investor'
    messages: List[ChatMessage] = []
    total_tokens_used: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ComplianceLog(BaseModel):
    """Auditoría legal inmutable (Ej. Solicitudes de exclusión / Opt-Out)"""
    lead_id: str
    company_id: str
    action: str # ej. 'opt-out_requested', 'data_deletion'
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)