from sqlalchemy import Column, String, Boolean, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.db.postgres import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(150), nullable=False)
    
    plan_id = Column(String(36), ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True)
    
    license_start = Column(DateTime, default=datetime.utcnow)
    license_end = Column(DateTime, nullable=True)
    payment_receipt_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 🚀 AÑADE ESTAS DOS LÍNEAS PARA GUARDAR EL CONSUMO DE OPENROUTER
    ai_tokens_used = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)

    # Relaciones
    plan = relationship("SubscriptionPlan")
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")