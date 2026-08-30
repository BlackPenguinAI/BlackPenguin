from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.db.postgres import Base


class SeoAuditRun(Base):
    __tablename__ = "seo_audit_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_url = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False)
    score = Column(Integer, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
