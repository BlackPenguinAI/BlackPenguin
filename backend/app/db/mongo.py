from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from bson import ObjectId
from app.core.config import settings

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

# Instancia global del manager
db_manager = MongoDBManager()

# Modelo Base para esquemas de Mongo (Manejo de ObjectIds)
class MongoBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str, datetime: lambda dt: dt.isoformat()}
    )