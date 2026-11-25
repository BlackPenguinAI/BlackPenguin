"""Durable Hermes P04 execution receipts, separate from the retired agent graph."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint
from app.db.postgres import Base


class HermesSalesOperation(Base):
    __tablename__ = 'hermes_sales_operations'
    __table_args__ = (
        UniqueConstraint('conversation_id','lead_id','request_id',name='uq_hermes_sales_operation_request'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id',ondelete='CASCADE'),nullable=False,index=True)
    project_id = Column(String(36), ForeignKey('projects.id',ondelete='CASCADE'),nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id',ondelete='CASCADE'),nullable=False)
    inbound_message_id = Column(String(36), ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False)
    request_id = Column(String(64), nullable=False)
    operation_type = Column(String(24),nullable=False)
    request_hash = Column(String(64),nullable=False)
    status = Column(String(24),nullable=False)
    result_json = Column(JSON,nullable=False,default=dict)
    created_at = Column(DateTime(timezone=True),nullable=False,default=lambda: datetime.now(timezone.utc))
