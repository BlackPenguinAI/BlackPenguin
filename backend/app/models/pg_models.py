from sqlalchemy import Column, String, Boolean, DateTime, Integer, Numeric, ForeignKey, Text, Enum as SqlaEnum, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import enum
import uuid
from datetime import datetime
from app.core.config import settings

Base = declarative_base()
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class PlanTier(str, enum.Enum):
    CORE = "core"
    ENTERPRISE = "enterprise"

class SpecializedAgentType(str, enum.Enum):
    LEASING = "leasing"
    INVESTOR = "investor"
    RETENTION = "retention"
    FINANCING = "financing"

class UserRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MKT = "mkt"
    SALES = "sales"

# =========================================================
# ETAPAS DEL EMBUDO DE VENTAS (LEADS)
# =========================================================
class FunnelStage(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    APPOINTMENT_SET = "appointment_set"
    CLOSED = "closed"
    LOST = "lost"

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(150), nullable=False)
    license_start = Column(DateTime, nullable=False)
    license_end = Column(DateTime, nullable=False)
    plan_tier = Column(SqlaEnum(PlanTier), default=PlanTier.CORE, nullable=False)
    max_projects_allowed = Column(Integer, default=1, nullable=False)
    has_voice_agents = Column(Boolean, default=False, nullable=False)
    has_property_tour = Column(Boolean, default=False, nullable=False)
    has_enterprise_integrations = Column(Boolean, default=False, nullable=False)
    voice_minutes_allowance = Column(Integer, default=0, nullable=False)
    offline_payment_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="company", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SqlaEnum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    company = relationship("Company", back_populates="users")

# =========================================================
# TABLA: PROYECTOS INMOBILIARIOS
# =========================================================
class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    company = relationship("Company", back_populates="projects")

# =========================================================
# NUEVA TABLA: ENRUTAMIENTO INTELIGENTE DE META ADS
# =========================================================
class MetaFormMapping(Base):
    __tablename__ = "meta_form_mappings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    meta_form_id = Column(String(100), unique=True, nullable=False, index=True) # ID del form de Facebook
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    company = relationship("Company")
    project = relationship("Project")

# =========================================================
# TABLA: LEADS (PROSPECTOS)
# =========================================================
class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    email = Column(String(150), nullable=True)
    source = Column(String(50), nullable=False) # ej. 'meta_ads', 'google_ads', 'landing_page'
    intent_score = Column(Numeric(5,2), default=0.0, nullable=False)
    is_opt_out = Column(Boolean, default=False, nullable=False)
    funnel_stage = Column(SqlaEnum(FunnelStage), default=FunnelStage.NEW, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    company = relationship("Company")
    project = relationship("Project")

# =========================================================
# GENERADOR DE SESIONES DE BASE DE DATOS
# =========================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =========================================================
# TABLA: MESSAGES (HISTORIAL DE CONVERSACIONES IA)
# =========================================================
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False) # 'system', 'user', 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relación inversa opcional hacia el Lead
    lead = relationship("Lead")