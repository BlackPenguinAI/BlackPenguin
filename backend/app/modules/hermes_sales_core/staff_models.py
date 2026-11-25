"""Single global Hermes configuration and immutable publication history (P05).

Never contains API credentials or company-specific overrides. Legacy Sales
configuration is deliberately left untouched until the P08 cutover.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Boolean, event
from app.db.postgres import Base


def utc_now():
    return datetime.now(timezone.utc)


class HermesGlobalSettings(Base):
    __tablename__ = 'hermes_global_settings'
    id = Column(String(16), primary_key=True)
    last_version = Column(Integer, nullable=False, default=0)
    published_version_id = Column(String(36), nullable=True)
    configuration = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class HermesGlobalVersion(Base):
    __tablename__ = 'hermes_global_versions'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version = Column(Integer, nullable=False, unique=True)
    configuration = Column(JSON, nullable=False)
    change_note = Column(String(500), nullable=False, default='')
    created_by_user_id = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    published_at = Column(DateTime(timezone=True), nullable=True)
    is_published = Column(Boolean, nullable=False, default=False)


@event.listens_for(HermesGlobalVersion, 'before_delete')
def _prevent_version_deletion(*_):
    raise ValueError('Hermes configuration versions are auditable and cannot be deleted')
