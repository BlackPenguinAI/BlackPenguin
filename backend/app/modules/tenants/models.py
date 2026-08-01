from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Integer, Enum as SqlaEnum, JSON
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
    
    # 🚀 NUEVO: Relación 1:1 con el Perfil Cognitivo
    profile = relationship("CompanyProfile", back_populates="company", uselist=False, cascade="all, delete-orphan")

# =========================================================================
# 🏢 3. THE COGNITIVE BRAIN: DETAILED CORPORATE PROFILE (7 SECTIONS)
# =========================================================================
class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # 🔗 Web Scraping Tracking
    scraped_source_url = Column(String(255), nullable=True)
    
    # 📊 SECTION 1: Company Identity
    legal_name = Column(String(205), nullable=True)
    dba = Column(String(150), nullable=True)
    headquarters = Column(String(255), nullable=True)
    year_established = Column(Integer, nullable=True)
    
    # 👥 SECTION 2: Executive Team & Key Contacts
    executive_team = Column(JSON, default=list)
    
    # 🏗️ SECTION 3: Core Focus & Asset Classes
    asset_classes = Column(JSON, default=list)
    core_focus_description = Column(Text, nullable=True)
    
    # 🗺️ SECTION 4: Market Coverage & Target Demographics
    market_coverage = Column(Text, nullable=True)
    target_demographics = Column(Text, nullable=True)
    
    # 💰 SECTION 5: Investment Strategy & Portfolio Size
    portfolio_size_aum = Column(String(100), nullable=True)
    investment_strategy = Column(Text, nullable=True)
    
    # 🏆 SECTION 6: Value Proposition & Differentiators
    value_proposition = Column(Text, nullable=True)
    key_differentiators = Column(Text, nullable=True)
    
    # 🎨 SECTION 7: Brand Guidelines
    tone_of_voice = Column(String(100), nullable=True)
    key_messaging = Column(Text, nullable=True)
    
    # 🏁 Onboarding Milestone Tracking
    is_identity_completed = Column(Boolean, default=False, nullable=False)
    is_team_completed = Column(Boolean, default=False, nullable=False)
    is_focus_completed = Column(Boolean, default=False, nullable=False)
    is_market_completed = Column(Boolean, default=False, nullable=False)
    is_strategy_completed = Column(Boolean, default=False, nullable=False)
    is_value_prop_completed = Column(Boolean, default=False, nullable=False)
    is_brand_completed = Column(Boolean, default=False, nullable=False)
    
    is_profile_fully_completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="profile")

# =========================================================
# 🧠 4. PROTOCOLOS DE ONBOARDING (Configurados por Staff)
# =========================================================
class OnboardingProtocol(Base):
    __tablename__ = "onboarding_protocols"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version = Column(Integer, default=1, nullable=False)
    description = Column(String(255), nullable=True)
    
    # Prompts para la Empresa (Company)
    system_role_prompt = Column(Text, nullable=False)   
    protocol_flow_prompt = Column(Text, nullable=False) 
    guardrails_prompt = Column(Text, nullable=False)    
    
    # 🚀 NUEVO: Prompts para Proyectos Inmobiliarios (Technical/Commercial/Inventory)
    project_system_prompt = Column(Text, nullable=True)
    project_protocol_prompt = Column(Text, nullable=True)
    project_guardrails_prompt = Column(Text, nullable=True)
    
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# =========================================================
# 💬 5. SESIONES Y MENSAJES DEL CHAT (Historial por Cliente)
# =========================================================
class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    messages = relationship("OnboardingMessage", back_populates="session", cascade="all, delete-orphan")

class OnboardingMessage(Base):
    __tablename__ = "onboarding_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False) 
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    session = relationship("OnboardingSession", back_populates="messages")