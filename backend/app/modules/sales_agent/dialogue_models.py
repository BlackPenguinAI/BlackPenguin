"""Additive dialogue storage; no backfill or change to live conversations."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Integer, JSON, DateTime, ForeignKey, UniqueConstraint, event
from app.db.postgres import Base


class SalesDialogueState(Base):
    __tablename__ = 'sales_dialogue_states'
    __table_args__ = (UniqueConstraint('conversation_id', 'lead_id', name='uq_dialogue_state_scope'),)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    schema_version = Column(String(40), nullable=False, default='sales-dialogue/1.0')
    state_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SalesDialogueEvent(Base):
    __tablename__ = 'sales_dialogue_events'
    __table_args__ = (UniqueConstraint('conversation_id', 'lead_id', 'event_key', name='uq_dialogue_event_key'),
                     UniqueConstraint('conversation_id', 'lead_id', 'revision', name='uq_dialogue_event_revision'))
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(String(36), ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(String(36), ForeignKey('sales_conversations.id', ondelete='CASCADE'), nullable=False)
    lead_id = Column(String(36), ForeignKey('leads.id', ondelete='CASCADE'), nullable=False)
    event_key = Column(String(120), nullable=False)
    revision = Column(Integer, nullable=False)
    kind = Column(String(40), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    payload_json = Column(JSON, nullable=False)
    state_after = Column(JSON, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


@event.listens_for(SalesDialogueEvent, 'before_update')
@event.listens_for(SalesDialogueEvent, 'before_delete')
def preserve_event(mapper, connection, target):
    raise ValueError('Dialogue evidence is append-only; do not update or delete events through the ORM.')
