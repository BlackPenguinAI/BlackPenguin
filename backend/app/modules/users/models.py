from sqlalchemy import Column, String, Boolean, ForeignKey, Enum as SqlaEnum, Date
from sqlalchemy.orm import relationship
import enum
import uuid
from app.db.postgres import Base

class UserRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MKT = "mkt"
    SALES = "sales"

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(100), nullable=True)
    
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    role = Column(SqlaEnum(UserRole), default=UserRole.ADMIN, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # string-based relationship para evitar ciclos
    company = relationship("Company", back_populates="users")