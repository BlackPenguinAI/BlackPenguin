from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
import uuid
from datetime import datetime
from app.db.postgres import Base

# =========================================================
# 🚀 TABLA MAESTRA: Inteligencia Distribuida (Multi-Agentes)
# =========================================================
class AIConfiguration(Base):
    __tablename__ = "ai_configurations"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    
    openrouter_api_key = Column(String(255), nullable=True)
    available_models = Column(JSON, default=list)
    
    # 🚀 AGENTES EN BLANCO: Diccionarios de los 4 agentes
    agent_onboarding_empresa = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_onboarding_proyectos = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_ventas = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    agent_reporteria = Column(JSON, default=lambda: {"model": "", "system_prompt": "", "protocol_prompt": "", "guardrails_prompt": ""})
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)