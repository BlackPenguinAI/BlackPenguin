from sqlalchemy import Column, String, Integer, DateTime
import uuid
from datetime import datetime
from app.db.postgres import Base

# =========================================================
# ⚙️ CONFIGURACIÓN GLOBAL DEL SISTEMA
# =========================================================
class SmtpConfig(Base):
    __tablename__ = "smtp_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, default=587, nullable=False)
    smtp_user = Column(String(255), nullable=False)
    smtp_password = Column(String(255), nullable=False)
    smtp_security = Column(String(10), default="TLS", nullable=False) # TLS, SSL, NONE
    sender_email = Column(String(255), nullable=False)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)