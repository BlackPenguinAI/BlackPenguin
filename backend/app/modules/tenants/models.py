from sqlalchemy import Column, String, Boolean, DateTime, Integer, Enum as SqlaEnum
from sqlalchemy.orm import relationship
import enum
import uuid
from datetime import datetime
from app.db.postgres import Base

class PlanTier(str, enum.Enum):
    CORE = "core"
    ENTERPRISE = "enterprise"

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    license_start = Column(DateTime, default=datetime.utcnow, nullable=False)
    license_end = Column(DateTime, nullable=False)
    plan_tier = Column(SqlaEnum(PlanTier), default=PlanTier.CORE, nullable=False)
    max_projects_allowed = Column(Integer, default=3, nullable=False)
    has_voice_agents = Column(Boolean, default=False, nullable=False)
    has_enterprise_integrations = Column(Boolean, default=False, nullable=False)
    voice_minutes_allowance = Column(Integer, default=0, nullable=False)
    offline_payment_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relación inversa hacia usuarios (String reference para evitar dependencias circulares)
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")