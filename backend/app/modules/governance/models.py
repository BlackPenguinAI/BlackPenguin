from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text

from app.db.postgres import Base


def _id() -> str:
    return str(uuid.uuid4())


class LegalDocumentVersion(Base):
    __tablename__ = "legal_document_versions"
    __table_args__ = (UniqueConstraint("doc_type", "language", "version", name="uq_legal_document_version"),)

    id = Column(String(36), primary_key=True, default=_id)
    doc_type = Column(String(50), nullable=False, index=True)
    language = Column(String(10), nullable=False, default="en")
    version = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    content_markdown = Column(Text, nullable=False)
    published_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserLegalAcceptance(Base):
    __tablename__ = "user_legal_acceptances"
    __table_args__ = (UniqueConstraint("user_id", "invitation_id", name="uq_user_invitation_legal_acceptance"),)

    id = Column(String(36), primary_key=True, default=_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    invitation_id = Column(String(36), ForeignKey("user_invitations.id", ondelete="SET NULL"), nullable=True)
    privacy_version_id = Column(String(36), ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False)
    terms_version_id = Column(String(36), ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False)
    data_deletion_version_id = Column(String(36), ForeignKey("legal_document_versions.id", ondelete="RESTRICT"), nullable=False)
    ip_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    accepted_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_events"

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_role = Column(String(30), nullable=True)
    event_type = Column(String(80), nullable=False, index=True)
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(36), nullable=True, index=True)
    reason = Column(Text, nullable=True)
    payload_json = Column(JSON, default=dict, nullable=False)
    request_id = Column(String(100), nullable=True, index=True)
    ip_hash = Column(String(64), nullable=True)
    previous_hash = Column(String(64), nullable=True)
    event_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class DataExportAuditEvent(Base):
    __tablename__ = "data_export_audit_events"

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_role = Column(String(30), nullable=False)
    export_type = Column(String(40), nullable=False, index=True)
    filters_json = Column(JSON, default=dict, nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    content_hash = Column(String(64), nullable=True)
    outcome = Column(String(30), nullable=False, default="generated", index=True)
    request_id = Column(String(100), nullable=True, index=True)
    ip_hash = Column(String(64), nullable=True)
    previous_hash = Column(String(64), nullable=True)
    event_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class AgentOperatingPolicy(Base):
    __tablename__ = "agent_operating_policies"
    __table_args__ = (
        UniqueConstraint("company_id", "project_id", name="uq_agent_operating_policy_scope"),
        Index(
            "uq_agent_operating_policy_company_default", "company_id", unique=True,
            postgresql_where=text("project_id IS NULL"), sqlite_where=text("project_id IS NULL"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    timezone = Column(String(80), nullable=False, default="UTC")
    weekly_windows = Column(JSON, default=dict, nullable=False)
    blackout_dates = Column(JSON, default=list, nullable=False)
    enforce_manual_messages = Column(Boolean, default=False, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    updated_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class KnowledgeGuidanceItem(Base):
    __tablename__ = "knowledge_guidance_items"

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String(20), nullable=False, index=True)
    title = Column(String(220), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(JSON, default=list, nullable=False)
    status = Column(String(20), default="draft", nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ConversationKpiTarget(Base):
    __tablename__ = "conversation_kpi_targets"
    __table_args__ = (
        UniqueConstraint("company_id", "project_id", name="uq_conversation_kpi_target_scope"),
        Index(
            "uq_conversation_kpi_target_company_default", "company_id", unique=True,
            postgresql_where=text("project_id IS NULL"), sqlite_where=text("project_id IS NULL"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    response_rate_percent = Column(Integer, nullable=False, default=30)
    conversation_turns_min = Column(Integer, nullable=False, default=2)
    conversation_turns_max = Column(Integer, nullable=False, default=12)
    updated_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class HumanInterventionCase(Base):
    __tablename__ = "human_intervention_cases"
    __table_args__ = (UniqueConstraint("conversation_id", "dedupe_key", name="uq_intervention_case_dedupe"),)

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("sales_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(String(60), nullable=False, index=True)
    evidence = Column(Text, nullable=True)
    confidence = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    dedupe_key = Column(String(160), nullable=False)
    resolved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("recipient_user_id", "dedupe_key", name="uq_notification_recipient_dedupe"),)

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    recipient_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type = Column(String(60), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="info")
    title = Column(String(180), nullable=False)
    body = Column(Text, nullable=False)
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(36), nullable=True)
    action_url = Column(String(500), nullable=True)
    dedupe_key = Column(String(180), nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(36), nullable=True)
    payload_json = Column(JSON, default=dict, nullable=False)
    dedupe_key = Column(String(180), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AppointmentEmailOutbox(Base):
    __tablename__ = "appointment_email_outbox"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_appointment_email_outbox_dedupe"),)

    id = Column(String(36), primary_key=True, default=_id)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    meeting_id = Column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=False)
    recipient_kind = Column(String(20), nullable=False)
    dedupe_key = Column(String(180), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(120), nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    delivery_status = Column(String(30), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SalesAssetAccessEvent(Base):
    __tablename__ = "sales_asset_access_events"

    id = Column(String(36), primary_key=True, default=_id)
    share_id = Column(String(36), ForeignKey("sales_asset_shares.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(20), nullable=False, index=True)
    ip_hash = Column(String(64), nullable=True)
    user_agent_hash = Column(String(64), nullable=True)
    is_automated = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
