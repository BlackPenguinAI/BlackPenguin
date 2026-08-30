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
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    COMPLETED_SALE_PENDING = "completed_sale_pending"
    SALE_CLOSED = "sale_closed"
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
    contact_id = Column(String(36), ForeignKey("lead_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    
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
    intent_tier = Column(String(20), default="cold", nullable=False, index=True)
    assigned_segment = Column(String(60), nullable=True, index=True)
    buyer_type = Column(String(30), nullable=True)
    pipeline_stage = Column(String(40), default="S00_CAPTURE", nullable=False, index=True)
    is_opt_out = Column(Boolean, default=False)
    qualification_summary = Column(Text, nullable=True)
    meta_form_data = Column(JSON, default=dict, nullable=False)
    visit_recommendations = Column(Text, nullable=True)
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
    score_history = relationship("LeadScoreSnapshot", back_populates="lead", cascade="all, delete-orphan")
    segment_history = relationship("LeadSegmentAssignment", back_populates="lead", cascade="all, delete-orphan")
    objections = relationship("LeadObjection", back_populates="lead", cascade="all, delete-orphan")


class LeadContact(Base):
    __tablename__ = "lead_contacts"
    __table_args__ = (UniqueConstraint("company_id", "canonical_phone", name="uq_lead_contact_company_phone"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    canonical_phone = Column(String(50), nullable=False)
    full_name = Column(String(150), nullable=True)
    email = Column(String(150), nullable=True)
    preferred_language = Column(String(10), nullable=True)
    preferred_channel = Column(String(30), nullable=True)
    previous_projects = Column(JSON, default=list, nullable=False)
    lifetime_value = Column(Numeric(16, 2), nullable=True)
    vip_flag = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LeadScoreSnapshot(Base):
    __tablename__ = "lead_score_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    total_score = Column(Integer, nullable=False)
    assigned_tier = Column(String(20), nullable=False, index=True)
    factor_breakdown = Column(JSON, default=dict, nullable=False)
    scoring_version = Column(String(40), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    lead = relationship("Lead", back_populates="score_history")


class LeadSegmentAssignment(Base):
    __tablename__ = "lead_segment_assignments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    segment = Column(String(60), nullable=False, index=True)
    confidence = Column(Numeric(3, 2), nullable=False, default=0.0)
    reasons = Column(JSON, default=list, nullable=False)
    strategy_version = Column(String(40), nullable=False)
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    lead = relationship("Lead", back_populates="segment_history")


class LeadObjection(Base):
    __tablename__ = "lead_objections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    objection_type = Column(String(30), nullable=False, index=True)
    evidence = Column(Text, nullable=False)
    status = Column(String(20), default="open", nullable=False)
    occurrence_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    lead = relationship("Lead", back_populates="objections")


class LeadConsentEvent(Base):
    __tablename__ = "lead_consent_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(30), nullable=False)
    action = Column(String(30), nullable=False)
    source = Column(String(60), nullable=False)
    policy_version = Column(String(40), nullable=True)
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


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
    broker_id = Column(String(36), ForeignKey("brokers.id", ondelete="SET NULL"), nullable=True)
    assigned_sales_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    meeting_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=45, nullable=False)
    modality = Column(String(30), default="virtual", nullable=False)
    confirmation_status = Column(String(30), default="pending", nullable=False)
    calendar_sync_status = Column(String(30), default="not_connected", nullable=False)
    meeting_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    visit_notes = Column(Text, nullable=True)
    visit_details = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    sale_closed_at = Column(DateTime, nullable=True)
    status = Column(SqlaEnum(MeetingStatus), default=MeetingStatus.SCHEDULED, nullable=False)
    gcal_event_id = Column(String(255), nullable=True)  # ID del evento en Google Calendar
    is_demo = Column(Boolean, default=False, nullable=False, index=True)
    source = Column(String(40), default="manual", nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    lead = relationship("Lead", back_populates="meetings")
    attachments = relationship("MeetingAttachment", back_populates="meeting", cascade="all, delete-orphan")


class MeetingAttachment(Base):
    __tablename__ = "meeting_attachments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meeting_id = Column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(30), nullable=False)
    storage_path = Column(Text, nullable=False)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    meeting = relationship("Meeting", back_populates="attachments")


class SalesAvailabilityWindow(Base):
    __tablename__ = "sales_availability_windows"
    __table_args__ = (
        UniqueConstraint("user_id", "weekday", "start_time", "end_time", name="uq_sales_availability_window"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    weekday = Column(Integer, nullable=False)
    start_time = Column(String(5), nullable=False)
    end_time = Column(String(5), nullable=False)
    timezone = Column(String(80), default="UTC", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SalesAvailabilityBlock(Base):
    """Date-specific availability entered by a Sales user in the monthly calendar."""

    __tablename__ = "sales_availability_blocks"
    __table_args__ = (
        UniqueConstraint("user_id", "starts_at", "ends_at", name="uq_sales_availability_block"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=False, index=True)
    timezone = Column(String(80), default="UTC", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CalendarConnection(Base):
    """Provider-neutral calendar connection metadata.

    OAuth secrets remain server-side.  The simulation can exercise calendar-ready
    scheduling without sending an external event.
    """

    __tablename__ = "calendar_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_calendar_connection_user_provider"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(30), nullable=False)
    calendar_id = Column(String(255), nullable=True)
    access_token_ciphertext = Column(Text, nullable=True)
    refresh_token_ciphertext = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    scopes = Column(JSON, default=list, nullable=False)
    sync_token = Column(Text, nullable=True)
    watch_channel_id = Column(String(255), nullable=True)
    watch_resource_id = Column(String(255), nullable=True)
    watch_expires_at = Column(DateTime, nullable=True)
    status = Column(String(30), default="simulation", nullable=False)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
