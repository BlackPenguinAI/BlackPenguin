from sqlalchemy import Column, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SqlaEnum
from sqlalchemy.orm import relationship
import enum
import uuid
from datetime import datetime
from app.db.postgres import Base

class FunnelStage(str, enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    APPOINTMENT_SET = "appointment_set"
    CLOSED = "closed"
    LOST = "lost"

# 🚀 NUEVA TABLA: Correos de la Lista de Espera
class WaitlistEmail(Base):
    __tablename__ = "waitlist_emails"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(150), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    email = Column(String(150), nullable=True)
    source = Column(String(50), nullable=False) 
    intent_score = Column(Numeric(5,2), default=0.0, nullable=False)
    is_opt_out = Column(Boolean, default=False, nullable=False)
    funnel_stage = Column(SqlaEnum(FunnelStage), default=FunnelStage.NEW, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)