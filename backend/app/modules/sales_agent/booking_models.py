"""Durable booking receipt and retryable Calendar operation, committed with the reservation."""
from datetime import datetime
import uuid
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey
from app.db.postgres import Base


class SalesBookingOperation(Base):
    __tablename__ = 'sales_booking_operations'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)
    proposal_id = Column(String(64), nullable=False, unique=True)
    meeting_id = Column(String(36), ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False, unique=True)
    snapshot_json = Column(JSON, nullable=False)
    calendar_status = Column(String(30), nullable=False, default='pending', index=True)
    calendar_attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_error = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
