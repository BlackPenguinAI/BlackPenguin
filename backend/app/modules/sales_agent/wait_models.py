"""One explicit, bounded alert request per lead; one immutable notice per request."""
from datetime import datetime
import uuid
from sqlalchemy import Column,String,Integer,DateTime,JSON,ForeignKey
from app.db.postgres import Base


class SalesWaitRequest(Base):
    __tablename__='sales_wait_requests'
    id=Column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    company_id=Column(String(36),ForeignKey('companies.id',ondelete='CASCADE'),nullable=False)
    project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False)
    target_project_id=Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False)
    conversation_id=Column(String(36),ForeignKey('sales_conversations.id',ondelete='CASCADE'),nullable=False)
    lead_id=Column(String(36),ForeignKey('leads.id',ondelete='CASCADE'),nullable=False)
    requested_message_id=Column(String(36),ForeignKey('sales_messages.id',ondelete='CASCADE'),nullable=False)
    active_key=Column(String(64),nullable=True,unique=True)
    request_key=Column(String(64),nullable=False)
    snapshot_json=Column(JSON,nullable=False)
    channel=Column(String(20),nullable=False)
    status=Column(String(30),nullable=False,default='waiting',index=True)
    close_reason=Column(String(100))
    expires_at=Column(DateTime(),nullable=False)
    next_check_at=Column(DateTime(),nullable=False,default=datetime.utcnow)
    lease_until=Column(DateTime())
    claim_token=Column(String(36))
    attempts=Column(Integer(),nullable=False,default=0)
    last_error=Column(String(100))
    scan_date=Column(String(10))
    notice_json=Column(JSON())
    anchor_revision=Column(Integer())
    anchor_inbound_id=Column(String(36))
    notified_message_id=Column(String(36),ForeignKey('sales_messages.id',ondelete='SET NULL'))
    created_at=Column(DateTime(),nullable=False,default=datetime.utcnow)
    closed_at=Column(DateTime())
