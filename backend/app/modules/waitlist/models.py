from sqlalchemy import Column, String, DateTime
import uuid
from datetime import datetime
from app.db.postgres import Base

class WaitlistEmail(Base):
    __tablename__ = "waitlist_emails"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(150), unique=True, nullable=False)
    language = Column(String(10), default="en") # Para saber de qué versión de landing llegó
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)