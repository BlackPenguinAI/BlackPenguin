from sqlalchemy import Column, String, Integer, DateTime, Text, JSON
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

# =========================================================
# 📄 GESTIÓN DE DOCUMENTOS LEGALES (Markdown)
# =========================================================
class LegalDocument(Base):
    __tablename__ = "legal_documents"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_type = Column(String(50), nullable=False) # 'privacy' o 'terms'
    language = Column(String(10), nullable=False, default="en") # 'en' o 'es'
    
    # 🚀 NUEVO: Campo específico para la etiqueta legible de actualización
    last_updated_label = Column(String(100), nullable=True, default="July 2026")
    
    content_markdown = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AiConfig(Base):
    __tablename__ = "system_ai_config"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Infraestructura
    openrouter_api_key = Column(String(255), nullable=True)
    available_models = Column(JSON, default=list)

    # Configuración de Agentes (JSON para almacenar dicts con model, system_prompt, etc.)
    agent_onboarding_empresa = Column(JSON, default=dict)
    agent_onboarding_proyectos = Column(JSON, default=dict)
    agent_ventas = Column(JSON, default=dict)
    agent_reporteria = Column(JSON, default=dict)