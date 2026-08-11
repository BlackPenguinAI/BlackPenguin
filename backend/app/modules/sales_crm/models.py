from sqlalchemy import Column, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SqlaEnum, Text, Float, JSON, Integer, UniqueConstraint
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
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"

class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("platform", "external_lead_id", name="uq_leads_platform_external_id"),
    )
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    campaign_id = Column(String(36), ForeignKey("project_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_sales_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    full_name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    email = Column(String(150), nullable=True)
    source = Column(String(50), default="Meta Ads", nullable=False)
    platform = Column(String(30), default="manual", nullable=False)
    external_lead_id = Column(String(180), nullable=True)
    preferred_channel = Column(String(30), nullable=True)
    channel_address = Column(String(180), nullable=True)
    consent_status = Column(String(30), default="unknown", nullable=False)
    consent_captured_at = Column(DateTime, nullable=True)
    
    intent_score = Column(Numeric(3, 2), default=0.0)
    is_opt_out = Column(Boolean, default=False)
    qualification_summary = Column(Text, nullable=True)
    agent_status = Column(String(30), default="paused", nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    funnel_stage = Column(SqlaEnum(FunnelStage), default=FunnelStage.NEW, nullable=False)
    last_interaction_at = Column(DateTime, nullable=True)
    stage_changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    next_action_at = Column(DateTime, nullable=True)
    
    # 📍 Geolocalización para el mapa de leads alrededor del proyecto
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones del módulo
    messages = relationship("SmsChatMessage", back_populates="lead", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="lead", cascade="all, delete-orphan")
    stage_history = relationship("LeadStageHistory", back_populates="lead", cascade="all, delete-orphan")


class LeadStageHistory(Base):
    __tablename__ = "lead_stage_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    from_stage = Column(String(40), nullable=True)
    to_stage = Column(String(40), nullable=False)
    actor_type = Column(String(30), nullable=False)
    actor_id = Column(String(36), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="stage_history")

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
    assigned_sales_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    meeting_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=45, nullable=False)
    modality = Column(String(30), default="virtual", nullable=False)
    confirmation_status = Column(String(30), default="pending", nullable=False)
    calendar_sync_status = Column(String(30), default="not_connected", nullable=False)
    meeting_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(SqlaEnum(MeetingStatus), default=MeetingStatus.SCHEDULED, nullable=False)
    gcal_event_id = Column(String(255), nullable=True)  # ID del evento en Google Calendar
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    lead = relationship("Lead", back_populates="meetings")
