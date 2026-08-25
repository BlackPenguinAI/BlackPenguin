from sqlalchemy import Column, String, Boolean, ForeignKey, Enum as SqlaEnum, Integer, Float
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

    # 🚀 CONSUMO INDIVIDUAL DE OPENROUTER
    ai_tokens_used = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)
    
    company = relationship("Company", back_populates="users")
