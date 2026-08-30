from sqlalchemy import Boolean, Column, Integer, String, DateTime, ForeignKey, JSON, UniqueConstraint
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


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("company_id", "agent_key", "version_number", name="uq_prompt_scope_agent_version"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    agent_key = Column(String(60), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    configuration = Column(JSON, nullable=False)
    is_published = Column(Boolean, default=True, nullable=False, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    published_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    change_note = Column(String(500), nullable=True)
