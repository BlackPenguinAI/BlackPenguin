from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Integer, Enum as SqlaEnum
from sqlalchemy.orm import relationship
import enum
import uuid
from datetime import datetime
from app.db.postgres import Base

class SenderType(str, enum.Enum):
    USER = "user"
    AI = "ai"   

# =========================================================
# 🚀 1. TABLA DE PLANES DE SUSCRIPCIÓN (Totalmente Dinámica)
# =========================================================
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    
    # Límites Máximos del Plan
    max_admins = Column(Integer, default=1, nullable=False)
    max_mkt_users = Column(Integer, default=0, nullable=False)
    max_sales_users = Column(Integer, default=0, nullable=False)
    max_projects = Column(Integer, default=1, nullable=False)
    max_properties_per_project = Column(Integer, default=50, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    companies = relationship("Company", back_populates="plan")

# =========================================================
# 🚀 2. TABLA DE EMPRESAS INMOBILIARIAS (Tenants)
# =========================================================
class Company(Base):
    __tablename__ = "companies"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(150), nullable=False)
    
    # Conexión al Plan
    plan_id = Column(String(36), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=True)
    plan = relationship("SubscriptionPlan", back_populates="companies")
    
    # Fechas y Vigencia
    license_start = Column(DateTime, default=datetime.utcnow, nullable=False)
    plan_duration_months = Column(Integer, default=12, nullable=False)
    license_end = Column(DateTime, nullable=False)
    
    # Estatus y Comprobante
    payment_receipt_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relaciones
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    projects = relationship("Project", overlaps="company", cascade="all, delete-orphan")

# =========================================================
# 🧠 1. PROTOCOLOS DE ONBOARDING (Configurados por Staff)
# =========================================================
class OnboardingProtocol(Base):
    __tablename__ = "onboarding_protocols"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version = Column(Integer, default=1, nullable=False)
    description = Column(String(255), nullable=True)
    
    # 🚀 Los 3 niveles de Prompt Estrictos
    system_role_prompt = Column(Text, nullable=False)   # Nivel 1: Identidad
    protocol_flow_prompt = Column(Text, nullable=False) # Nivel 2: Flujo de Atención
    guardrails_prompt = Column(Text, nullable=False)    # Nivel 3: Contexto Estricto
    
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# =========================================================
# 💬 2. SESIONES Y MENSAJES DEL CHAT (Historial por Cliente)
# =========================================================
class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relaciones
    messages = relationship("OnboardingMessage", back_populates="session", cascade="all, delete-orphan")

class OnboardingMessage(Base):
    __tablename__ = "onboarding_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False) # 'user' o 'ai'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    session = relationship("OnboardingSession", back_populates="messages")