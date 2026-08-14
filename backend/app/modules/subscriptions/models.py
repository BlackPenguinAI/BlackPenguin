from sqlalchemy import Column, String, Boolean, Integer, DateTime
from datetime import datetime
import uuid
from app.db.postgres import Base

class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(150), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    
    # Límites de Usuarios
    max_assistants = Column(Integer, default=0)
    max_mkt_users = Column(Integer, default=0)
    max_sales_users = Column(Integer, default=0)
    
    # Límites del Sistema
    max_projects = Column(Integer, default=1)
    max_property_types_per_project = Column(Integer, default=20)
    max_properties_per_project = Column(Integer, default=50)
    
    is_active = Column(Boolean, default=True)

    # 🚀 ESTA ES LA COLUMNA QUE FALTABA
    created_at = Column(DateTime, default=datetime.utcnow)
