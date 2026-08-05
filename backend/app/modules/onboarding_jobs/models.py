from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.db.postgres import Base


class OnboardingSourceJob(Base):
    __tablename__ = "onboarding_source_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_onboarding_source_jobs_idempotency"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope = Column(String(20), nullable=False, index=True)
    company_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=True, index=True)
    source_id = Column(String(36), nullable=False, index=True)
    message_id = Column(String(36), nullable=True)
    status = Column(String(20), default="queued", nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    error_code = Column(String(80), nullable=True)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    available_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
