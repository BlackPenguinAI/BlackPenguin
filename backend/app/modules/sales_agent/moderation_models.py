"""Evidence and warning receipts; a repeated webhook is not a second offence."""
from datetime import datetime
import uuid
from sqlalchemy import Column,String,DateTime,ForeignKey,UniqueConstraint
from app.db.postgres import Base


class SalesModerationIncident(Base):
    __tablename__='sales_moderation_incidents'
    __table_args__=(UniqueConstraint('conversation_id','event_key',name='uq_sales_moderation_event'),)
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    company_id=Column(String(36),ForeignKey('companies.id',ondelete='CASCADE'),nullable=False)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False)
    conversation_id=Column(String(36),ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False)
    lead_id=Column(String(36),ForeignKey('leads.id',ondelete='CASCADE'),nullable=False)
    message_id=Column(String(36),ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False)
    event_key=Column(String(300),nullable=False)
    category=Column(String(30),nullable=False)
    evidence=Column(String(2000),nullable=False)
    disposition=Column(String(30),nullable=False)
    prior_warning_id=Column(String(36),ForeignKey('sales_moderation_incidents.id',ondelete='SET NULL'))
    warning_message_id=Column(String(36),ForeignKey('sales_messages.id',ondelete='SET NULL'))
    warning_accepted_at=Column(DateTime())
    intervention_case_id=Column(String(36),ForeignKey('human_intervention_cases.id',ondelete='SET NULL'))
    dismissed_at=Column(DateTime())
    created_at=Column(DateTime(),nullable=False,default=datetime.utcnow)
