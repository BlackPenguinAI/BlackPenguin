from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class SalesConversation(Base):
    __tablename__ = "sales_conversations"
    __table_args__ = (UniqueConstraint("lead_id", "channel", name="uq_sales_conversation_lead_channel"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(String(36), ForeignKey("project_campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_thread_key = Column(String(220), nullable=True, unique=True, index=True)
    channel = Column(String(30), nullable=False)
    stage = Column(String(40), default="new", nullable=False, index=True)
    automation_level = Column(Integer, default=0, nullable=False)
    is_paused = Column(Boolean, default=True, nullable=False)
    pause_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship("SalesMessage", back_populates="conversation", cascade="all, delete-orphan")
    lead_contexts = relationship("SalesConversationLeadContext", back_populates="conversation", cascade="all, delete-orphan")


class SalesConversationLeadContext(Base):
    """Opportunity history for one physical sender/recipient SMS thread."""

    __tablename__ = "sales_conversation_lead_contexts"
    __table_args__ = (UniqueConstraint("conversation_id", "lead_id", name="uq_sales_conversation_lead_context"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    activated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("SalesConversation", back_populates="lead_contexts")


class SalesMessage(Base):
    __tablename__ = "sales_messages"
    __table_args__ = (UniqueConstraint("channel", "provider_message_id", name="uq_sales_message_provider_id"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(30), nullable=False)
    direction = Column(String(20), nullable=False)
    role = Column(String(20), nullable=False)
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    content = Column(Text, nullable=False)
    provider_message_id = Column(String(180), nullable=True)
    status = Column(String(30), default="received", nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    conversation = relationship("SalesConversation", back_populates="messages")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(180), unique=True, nullable=False)
    mode = Column(String(20), default="simulation", nullable=False)
    status = Column(String(30), default="running", nullable=False)
    graph_version = Column(String(30), nullable=False)
    toolset_version = Column(String(30), nullable=False)
    prompt_configuration_id = Column(String(36), nullable=True)
    prompt_snapshot = Column(JSON, nullable=False)
    model = Column(String(180), nullable=False)
    input_snapshot = Column(JSON, default=dict, nullable=False)
    output_snapshot = Column(JSON, default=dict, nullable=False)
    token_usage = Column(JSON, default=dict, nullable=False)
    estimated_cost_usd = Column(String(30), nullable=True)
    error_code = Column(String(80), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key = Column(String(220), unique=True, nullable=False)
    channel = Column(String(30), nullable=False)
    recipient = Column(String(180), nullable=True)
    content = Column(Text, nullable=False)
    provider_message_id = Column(String(180), nullable=True, unique=True, index=True)
    status = Column(String(30), default="draft", nullable=False, index=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalWebhookEvent(Base):
    __tablename__ = "external_webhook_events"
    __table_args__ = (UniqueConstraint("platform", "external_event_id", name="uq_webhook_platform_event"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform = Column(String(30), nullable=False)
    external_event_id = Column(String(180), nullable=False)
    event_type = Column(String(80), nullable=False)
    payload_json = Column(JSON, nullable=False)
    status = Column(String(30), default="received", nullable=False)
    error_message = Column(Text, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class SalesAgentSimulation(Base):
    """Auditable demo run that uses the same conversation engine as a real lead."""

    __tablename__ = "sales_agent_simulations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(String(36), ForeignKey("project_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True)
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(40), default="active", nullable=False, index=True)
    approval_status = Column(String(30), default="pending", nullable=False)
    approval_notes = Column(Text, nullable=True)
    form_snapshot = Column(JSON, default=dict, nullable=False)
    prompt_snapshot = Column(JSON, default=dict, nullable=False)
    virtual_now = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SalesFollowUpJob(Base):
    """Durable follow-up schedule; the demo advances it with a virtual clock."""

    __tablename__ = "sales_follow_up_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(220), nullable=False, unique=True)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(30), default="pending", nullable=False, index=True)
    reason = Column(String(120), nullable=False)
    attempt_number = Column(Integer, default=1, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
