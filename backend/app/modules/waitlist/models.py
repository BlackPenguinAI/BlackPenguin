from sqlalchemy import Column, String, DateTime, Boolean
import uuid
from datetime import datetime
from app.db.postgres import Base

class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True) # True = Pendiente de contacto
    created_at = Column(DateTime, default=datetime.utcnow)