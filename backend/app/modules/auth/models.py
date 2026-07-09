from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SqlaEnum, Date
from sqlalchemy.orm import relationship
import enum
import uuid
from datetime import datetime
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
    
    # --- IDENTIDAD ---
    full_name = Column(String(150), nullable=True)
    last_name_paternal = Column(String(100), nullable=True)
    last_name_maternal = Column(String(100), nullable=True)
    document_type = Column(String(20), nullable=True) # DNI, Pasaporte, RUT, etc.
    document_number = Column(String(50), nullable=True)
    birth_date = Column(Date, nullable=True)
    
    # --- CONTACTO ---
    email = Column(String(150), unique=True, index=True, nullable=False)
    phone = Column(String(50), nullable=True)
    
    # --- UBICACIÓN ---
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    
    # --- SISTEMA ---
    hashed_password = Column(String(255), nullable=False)
    role = Column(SqlaEnum(UserRole), default=UserRole.SALES, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    company = relationship("Company", back_populates="users")