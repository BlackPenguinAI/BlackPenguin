from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from app.db.postgres import Base

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id = Column(String(36), ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True)
    
    name = Column(String(150), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    license_start = Column(DateTime, default=datetime.utcnow, nullable=False)
    license_end = Column(DateTime, nullable=False)
    
    # 🚀 RUTA DEL COMPROBANTE DE PAGO
    payment_receipt_url = Column(String(255), nullable=True) 
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    plan = relationship("SubscriptionPlan", back_populates="companies")
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")