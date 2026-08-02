from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SqlaEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.postgres import Base


class SenderType(str, enum.Enum):
    USER = "user"
    AI = "ai"


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("OnboardingSession", back_populates="messages")
