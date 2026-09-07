from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SqlaEnum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class SenderType(str, enum.Enum):
    USER = "user"
    AI = "ai"


class SourceKind(str, enum.Enum):
    OFFICIAL_WEBSITE = "official_website"
    SOCIAL_PROFILE = "social_profile"
    ONLINE_DOCUMENT = "online_document"
    THIRD_PARTY = "third_party"
    UPLOADED_FILE = "uploaded_file"


class SourceStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class CompanyProfile(Base):
    __tablename__ = "company_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Legacy fields retained during the migration.
    legal_name = Column(String(255), nullable=True)
    dba = Column(String(255), nullable=True)
    headquarters = Column(String(255), nullable=True)
    year_established = Column(String(4), nullable=True)
    executive_team = Column(JSON, default=list)
    asset_classes = Column(JSON, default=list)
    market_coverage = Column(String(255), nullable=True)
    target_demographics = Column(Text, nullable=True)
    aum = Column(String(100), nullable=True)
    investment_strategy = Column(Text, nullable=True)
    value_proposition = Column(Text, nullable=True)
    key_differentiators = Column(Text, nullable=True)
    tone_of_voice = Column(String(100), nullable=True)
    key_messaging = Column(Text, nullable=True)

    # Canonical Company Onboarding data and per-field validation state.
    profile_data = Column(JSON, default=dict, nullable=False)
    field_states = Column(JSON, default=dict, nullable=False)
    field_sources = Column(JSON, default=dict, nullable=False)
    final_approved = Column(Boolean, default=False, nullable=False)
    completion_percentage = Column(Integer, default=0, nullable=False)

    # Legacy flags retained temporarily for backward compatibility.
    is_identity_completed = Column(Boolean, default=False)
    is_team_completed = Column(Boolean, default=False)
    is_focus_completed = Column(Boolean, default=False)
    is_market_completed = Column(Boolean, default=False)
    is_strategy_completed = Column(Boolean, default=False)
    is_value_prop_completed = Column(Boolean, default=False)
    is_brand_completed = Column(Boolean, default=False)
    is_profile_fully_completed = Column(Boolean, default=False)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship("OnboardingMessage", back_populates="session", cascade="all, delete-orphan")


class OnboardingMessage(Base):
    __tablename__ = "onboarding_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("onboarding_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False)
    content = Column(Text, nullable=False)
    ui_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    media_evidence = Column(JSON, nullable=True)
    in_reply_to_message_id = Column(String(36), ForeignKey("onboarding_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("OnboardingSession", back_populates="messages")
    attachments = relationship("CompanyOnboardingSource", back_populates="message", passive_deletes=True)


class CompanyOnboardingSource(Base):
    __tablename__ = "company_onboarding_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("onboarding_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(SqlaEnum(SourceKind), nullable=False)
    status = Column(SqlaEnum(SourceStatus), default=SourceStatus.PROCESSING, nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=True)
    mime_type = Column(String(150), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True, index=True)
    original_filename = Column(String(255), nullable=True)
    stored_filename = Column(String(255), nullable=True)
    storage_path = Column(Text, nullable=True)
    extracted_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_stage = Column(String(40), default="queued", nullable=False)
    processing_detail = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    proposals = relationship(
        "CompanyOnboardingProposal",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    message = relationship("OnboardingMessage", back_populates="attachments")


class CompanyOnboardingProposal(Base):
    __tablename__ = "company_onboarding_proposals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(
        String(36),
        ForeignKey("company_onboarding_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_key = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    evidence = Column(Text, nullable=True)
    confidence = Column(String(20), nullable=True)
    status = Column(SqlaEnum(ProposalStatus), default=ProposalStatus.PENDING, nullable=False)
    reviewed_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source = relationship("CompanyOnboardingSource", back_populates="proposals")


class CompanyMediaAsset(Base):
    __tablename__ = "company_media_assets"
    __table_args__ = (
        UniqueConstraint("company_id", "sha256", name="uq_company_media_company_sha256"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("company_onboarding_sources.id", ondelete="SET NULL"), nullable=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role = Column(String(30), default="logo_candidate", nullable=False, index=True)
    name = Column(String(255), nullable=False)
    mime_type = Column(String(150), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_path = Column(Text, nullable=False)
    source_url = Column(Text, nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    review_status = Column(String(30), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    source = relationship("CompanyOnboardingSource")
