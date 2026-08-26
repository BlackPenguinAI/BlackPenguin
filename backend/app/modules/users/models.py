from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SqlaEnum, Integer, Float, UniqueConstraint
from sqlalchemy.orm import relationship
import enum
import uuid
from app.db.postgres import Base

class UserRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    ASSISTANT = "assistant"
    MKT = "mkt"
    SALES = "sales"


# Assistants currently share the tenant workspace capabilities of the Company
# administrator.  The administrator identity itself remains unique and can only
# be managed through the superadmin Company workflow.
TENANT_MANAGER_ROLES = [UserRole.ADMIN, UserRole.ASSISTANT]

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    country = Column(String(100), nullable=True)
    timezone = Column(String(80), default="UTC", nullable=False)
    
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    role = Column(SqlaEnum(UserRole), default=UserRole.ADMIN, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    project_access_scope = Column(String(20), default="all", nullable=False)

    # 🚀 CONSUMO INDIVIDUAL DE OPENROUTER
    ai_tokens_used = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)
    
    company = relationship("Company", back_populates="users")
    project_access = relationship("UserProjectAccess", back_populates="user", cascade="all, delete-orphan")


class UserProjectAccess(Base):
    __tablename__ = "user_project_access"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_project_access"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="project_access")
    project = relationship("Project")
