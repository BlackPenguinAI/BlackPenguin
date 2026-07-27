from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, JSON, Integer, Enum as SqlaEnum
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
import enum
from app.db.postgres import Base

# Importamos SenderType de tenants para reusar la lógica (user vs ai)
from app.modules.tenants.models import SenderType

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
    
    company = relationship("Company")
    
    # 🚀 RELACIONES NUEVAS: Perfil y Sesión de Onboarding
    profile = relationship("ProjectProfile", back_populates="project", uselist=False, cascade="all, delete-orphan")
    session = relationship("ProjectSession", back_populates="project", uselist=False, cascade="all, delete-orphan")


# =========================================================================
# 🏢 DATA EXTRACTOR: LOS 3 PILARES DEL PROYECTO
# =========================================================================
class ProjectProfile(Base):
    __tablename__ = "project_profiles"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # 🏗️ PILAR A: Detalles Técnicos
    typologies = Column(JSON, default=list) # ej. [{"m2": 60, "rooms": 2, "baths": 2}]
    amenities = Column(JSON, default=list)
    construction_details = Column(Text, nullable=True)
    
    # 💰 PILAR B: Detalles Comerciales
    price_from = Column(String(100), nullable=True)
    payment_methods = Column(Text, nullable=True)
    discounts = Column(Text, nullable=True)
    delivery_dates = Column(Text, nullable=True)
    
    # 📦 PILAR C: Inventario
    available_units = Column(String(255), nullable=True)
    sales_phases = Column(Text, nullable=True)
    
    # 🏁 Hitos de completitud
    is_technical_completed = Column(Boolean, default=False)
    is_commercial_completed = Column(Boolean, default=False)
    is_inventory_completed = Column(Boolean, default=False)
    is_fully_completed = Column(Boolean, default=False)
    
    project = relationship("Project", back_populates="profile")


# =========================================================================
# 💬 CHAT DE ONBOARDING ESPECÍFICO DEL PROYECTO
# =========================================================================
class ProjectSession(Base):
    __tablename__ = "project_sessions"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    project = relationship("Project", back_populates="session")
    messages = relationship("ProjectMessage", back_populates="session", cascade="all, delete-orphan")

class ProjectMessage(Base):
    __tablename__ = "project_messages"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("project_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False) 
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    session = relationship("ProjectSession", back_populates="messages")