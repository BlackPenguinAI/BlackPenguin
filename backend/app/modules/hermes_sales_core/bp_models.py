"""Additive P03 state/event tables. No changes to LangGraph dialogue tables."""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event
from app.db.postgres import Base


class HermesSalesState(Base):
    __tablename__ = 'hermes_sales_states'
    __table_args__ = (UniqueConstraint('conversation_id', 'lead_id', name='uq_hermes_state_opportunity'),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)
    engine_version = Column(String(64), nullable=False, default='hermes-sales-core/0.2-p02')
    schema_version = Column(String(40), nullable=False, default='hermes-sales-state/1.0')
    revision = Column(Integer, nullable=False, default=0)
    state_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class HermesSalesStateEvent(Base):
    __tablename__ = 'hermes_sales_state_events'
    __table_args__ = (
        UniqueConstraint('conversation_id', 'lead_id', 'event_key', name='uq_hermes_state_event_key'),
        UniqueConstraint('conversation_id', 'lead_id', 'revision', name='uq_hermes_state_event_revision'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)
    event_key = Column(String(120), nullable=False)
    revision = Column(Integer, nullable=False)
    event_type = Column(String(36), nullable=False)
    schema_version = Column(String(40), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    state_after = Column(JSON, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


@event.listens_for(HermesSalesStateEvent, 'before_update')
@event.listens_for(HermesSalesStateEvent, 'before_delete')
def _deny_mutation(mapper, connection, target):
    raise ValueError('Hermes state event history is append-only')
