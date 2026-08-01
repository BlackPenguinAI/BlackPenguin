from sqlalchemy import Column, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SqlaEnum, Text, Float
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

class MeetingStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    
    full_name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    email = Column(String(150), nullable=True)
    source = Column(String(50), default="Meta Ads", nullable=False)
    
    intent_score = Column(Numeric(3, 2), default=0.0)
    is_opt_out = Column(Boolean, default=False)
    funnel_stage = Column(SqlaEnum(FunnelStage), default=FunnelStage.NEW, nullable=False)
    
    # 📍 Geolocalización para el mapa de leads alrededor del proyecto
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones del módulo
    messages = relationship("SmsChatMessage", back_populates="lead", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="lead", cascade="all, delete-orphan")

class SmsChatMessage(Base):
    __tablename__ = "sms_chat_messages"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" o "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    lead = relationship("Lead", back_populates="messages")

class Meeting(Base):
    __tablename__ = "meetings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    broker_id = Column(String(36), ForeignKey("brokers.id", ondelete="CASCADE"), nullable=False)
    
    meeting_time = Column(DateTime, nullable=False)
    status = Column(SqlaEnum(MeetingStatus), default=MeetingStatus.SCHEDULED, nullable=False)
    gcal_event_id = Column(String(255), nullable=True)  # ID del evento en Google Calendar
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    lead = relationship("Lead", back_populates="meetings")