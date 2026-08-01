from sqlalchemy import Column, String, Boolean, Text, Integer
from sqlalchemy.orm import relationship
import uuid
from app.db.postgres import Base

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    
    max_admins = Column(Integer, default=1, nullable=False)
    max_mkt_users = Column(Integer, default=0, nullable=False)
    max_sales_users = Column(Integer, default=0, nullable=False)
    max_projects = Column(Integer, default=1, nullable=False)
    max_properties_per_project = Column(Integer, default=50, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Vinculación usando string "Company" para evitar dependencias circulares (DDD)
    companies = relationship("Company", back_populates="plan")