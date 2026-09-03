from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SqlaEnum, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class SenderType(str, enum.Enum):
    USER = "user"
    AI = "ai"


class ProjectSourceKind(str, enum.Enum):
    URL = "url"
    UPLOADED_FILE = "uploaded_file"
    IMAGE = "image"
    SPREADSHEET = "spreadsheet"


class ProjectSourceStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ProjectProposalStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_demo_template_per_company",
            "company_id",
            "demo_template_version",
            unique=True,
            postgresql_where=text("is_demo = true AND demo_template_version IS NOT NULL"),
            sqlite_where=text("is_demo = 1 AND demo_template_version IS NOT NULL"),
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    timezone = Column(String(80), default="UTC", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False, index=True)
    demo_template_version = Column(String(30), nullable=True)
    onboarding_status = Column(String(30), default="draft", nullable=False, index=True)
    onboarding_completed_at = Column(DateTime, nullable=True)
    onboarding_approved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    profile = relationship("ProjectProfile", back_populates="project", uselist=False, cascade="all, delete-orphan")
    session = relationship("ProjectSession", back_populates="project", uselist=False, cascade="all, delete-orphan")
    sources = relationship("ProjectOnboardingSource", back_populates="project", cascade="all, delete-orphan")
    campaigns = relationship("ProjectCampaign", back_populates="project", cascade="all, delete-orphan")
    units = relationship("ProjectUnit", back_populates="project", cascade="all, delete-orphan")
    property_types = relationship("ProjectPropertyType", back_populates="project", cascade="all, delete-orphan")


class ProjectProfile(Base):
    __tablename__ = "project_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Legacy columns kept for backward compatibility.
    typologies = Column(JSON, default=list)
    amenities = Column(JSON, default=list)
    construction_details = Column(Text, nullable=True)
    price_from = Column(String(100), nullable=True)
    payment_methods = Column(Text, nullable=True)
    discounts = Column(Text, nullable=True)
    delivery_dates = Column(Text, nullable=True)
    available_units = Column(String(255), nullable=True)
    sales_phases = Column(Text, nullable=True)
    is_technical_completed = Column(Boolean, default=False)
    is_commercial_completed = Column(Boolean, default=False)
    is_inventory_completed = Column(Boolean, default=False)
    is_fully_completed = Column(Boolean, default=False)

    profile_data = Column(JSON, default=dict, nullable=False)
    field_states = Column(JSON, default=dict, nullable=False)
    field_sources = Column(JSON, default=dict, nullable=False)
    completion_percentage = Column(Integer, default=0, nullable=False)
    final_approved = Column(Boolean, default=False, nullable=False)
    sales_activation_status = Column(String(30), default="not_ready", nullable=False)
    inventory_last_updated_at = Column(DateTime, nullable=True)
    approved_for_sales_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="profile")


class ProjectSession(Base):
    __tablename__ = "project_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="session")
    messages = relationship("ProjectMessage", back_populates="session", cascade="all, delete-orphan")


class ProjectMessage(Base):
    __tablename__ = "project_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("project_sessions.id", ondelete="CASCADE"), nullable=False)
    sender = Column(SqlaEnum(SenderType), nullable=False)
    content = Column(Text, nullable=False)
    ui_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    in_reply_to_message_id = Column(String(36), ForeignKey("project_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ProjectSession", back_populates="messages")
    attachments = relationship("ProjectOnboardingSource", back_populates="message", passive_deletes=True)


class ProjectOnboardingSource(Base):
    __tablename__ = "project_onboarding_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("project_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    kind = Column(SqlaEnum(ProjectSourceKind, name="projectsourcekind"), nullable=False)
    status = Column(SqlaEnum(ProjectSourceStatus, name="projectsourcestatus"), default=ProjectSourceStatus.PROCESSING, nullable=False)
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
    is_primary = Column(Boolean, default=False, nullable=False)
    focal_point_x = Column(Float, default=0.5, nullable=False)
    focal_point_y = Column(Float, default=0.5, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="sources")
    message = relationship("ProjectMessage", back_populates="attachments")
    proposals = relationship("ProjectOnboardingProposal", back_populates="source", cascade="all, delete-orphan")


class ProjectUnit(Base):
    __tablename__ = "project_units"
    __table_args__ = (UniqueConstraint("project_id", "unit_code", name="uq_project_units_project_code"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("project_onboarding_sources.id", ondelete="SET NULL"), nullable=True)
    unit_code = Column(String(100), nullable=False)
    typology = Column(String(150), nullable=True)
    tower_or_phase = Column(String(150), nullable=True)
    area = Column(Numeric(12, 2), nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    list_price = Column(Numeric(16, 2), nullable=True)
    currency = Column(String(10), nullable=True)
    status = Column(String(30), default="available", nullable=False, index=True)
    inventory_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="units")


class ProjectPropertyType(Base):
    __tablename__ = "project_property_types"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_property_types_project_name"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(180), nullable=False)
    code = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Float, nullable=True)
    area_min = Column(Numeric(12, 2), nullable=True)
    area_max = Column(Numeric(12, 2), nullable=True)
    area_unit = Column(String(20), nullable=True)
    total_units = Column(Integer, nullable=True)
    available_units = Column(Integer, nullable=True)
    starting_price = Column(Numeric(16, 2), nullable=True)
    maximum_price = Column(Numeric(16, 2), nullable=True)
    currency = Column(String(10), nullable=True)
    features = Column(JSON, default=list, nullable=False)
    inventory_updated_at = Column(DateTime, nullable=True)
    images_status = Column(String(30), default="pending", nullable=False)
    review_status = Column(String(30), default="confirmed", nullable=False)
    source_reference = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="property_types")
    media = relationship("ProjectPropertyTypeMedia", back_populates="property_type", cascade="all, delete-orphan")


class ProjectPropertyTypeMedia(Base):
    __tablename__ = "project_property_type_media"
    __table_args__ = (UniqueConstraint("property_type_id", "source_id", name="uq_property_type_media_source"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    property_type_id = Column(String(36), ForeignKey("project_property_types.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("project_onboarding_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    caption = Column(String(255), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    property_type = relationship("ProjectPropertyType", back_populates="media")
    source = relationship("ProjectOnboardingSource")


class SalesAssetShare(Base):
    __tablename__ = "sales_asset_shares"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("project_onboarding_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked = Column(Boolean, default=False, nullable=False)
    access_count = Column(Integer, default=0, nullable=False)
    last_accessed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProjectOnboardingProposal(Base):
    __tablename__ = "project_onboarding_proposals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(String(36), ForeignKey("project_onboarding_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    field_key = Column(String(100), nullable=False)
    value = Column(JSON, nullable=True)
    evidence = Column(Text, nullable=True)
    confidence = Column(String(20), nullable=True)
    status = Column(SqlaEnum(ProjectProposalStatus, name="projectproposalstatus"), default=ProjectProposalStatus.PENDING, nullable=False)
    reviewed_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source = relationship("ProjectOnboardingSource", back_populates="proposals")


class ProjectCampaign(Base):
    __tablename__ = "project_campaigns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    meta_connection_id = Column(String(36), ForeignKey("meta_connections.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(180), nullable=False)
    platform = Column(String(30), default="meta", nullable=False)
    objective = Column(String(100), nullable=True)
    status = Column(String(30), default="draft", nullable=False)
    external_campaign_id = Column(String(150), nullable=True)
    external_adset_id = Column(String(150), nullable=True)
    external_ad_id = Column(String(150), nullable=True)
    lead_form_id = Column(String(150), nullable=True)
    audience_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="campaigns")
    meta_connection = relationship("MetaConnection")


class MetaConnection(Base):
    __tablename__ = "meta_connections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    business_account_id = Column(String(150), nullable=True)
    ad_account_id = Column(String(150), nullable=True)
    page_id = Column(String(150), nullable=True)
    instagram_account_id = Column(String(150), nullable=True)
    token_ciphertext = Column(Text, nullable=True)
    token_hint = Column(String(12), nullable=True)
    scopes = Column(JSON, default=list, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verification_mode = Column(String(20), default="real", nullable=False)
    verification_status = Column(String(30), default="pending", nullable=False)
    verification_results = Column(JSON, default=dict, nullable=False)
    page_access_confirmed = Column(Boolean, default=False, nullable=False)
    ad_account_access_confirmed = Column(Boolean, default=False, nullable=False)
    leads_access_confirmed = Column(Boolean, default=False, nullable=False)
    simulated_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
