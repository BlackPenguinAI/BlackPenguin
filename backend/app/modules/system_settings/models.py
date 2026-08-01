from sqlalchemy import Column, String, DateTime, Text
import uuid
from datetime import datetime
from app.db.postgres import Base

# =========================================================
# ⚙️ CONFIGURACIÓN DE SERVICIOS EXTERNOS Y LEGALES
# =========================================================

class FirebaseConfig(Base):
    __tablename__ = "firebase_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key = Column(String(255), nullable=True)
    auth_domain = Column(String(255), nullable=True)
    project_id = Column(String(255), nullable=True)
    credentials_json = Column(Text, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TwilioConfig(Base):
    __tablename__ = "twilio_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_sid = Column(String(255), nullable=True)
    auth_token = Column(String(255), nullable=True)
    from_phone_number = Column(String(50), nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class LegalDocument(Base):
    __tablename__ = "legal_documents"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_type = Column(String(50), nullable=False)  # 'privacy' o 'terms'
    language = Column(String(10), nullable=False, default="en")  # 'en' o 'es'
    last_updated_label = Column(String(100), nullable=True, default="July 2026")
    content_markdown = Column(Text, nullable=False)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)