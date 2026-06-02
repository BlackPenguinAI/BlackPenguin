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
# NUEVA TABLA: PROYECTOS INMOBILIARIOS
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
# GENERADOR DE SESIONES DE BASE DE DATOS
# =========================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()