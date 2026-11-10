"""Opt-in PostgreSQL control/FIFO races. Disposable *_test databases only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from unittest.mock import patch
import os,uuid
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session,sessionmaker
import app.db.base
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.models import Project
from app.modules.sales_crm.models import Lead,Meeting
from app.modules.sales_agent.models import SalesConversation,SalesMessage,SalesFollowUpJob,SalesInboundJob,OutboundMessage
from app.modules.sales_agent import continuity,live_worker
from app.modules.sales_agent.service import set_conversation_action


@pytest.fixture
def postgres_case():
    url=os.environ.get('DIALOGUE_POSTGRES_TEST_URL')
    if not url:pytest.skip('Disposable PostgreSQL URL required for real control/FIFO races.')
    engine=create_engine(url)
    with engine.connect() as connection:
        assert connection.dialect.name=='postgresql' and connection.execute(text('SELECT current_database()')).scalar_one().endswith('_test')
    schema='bp_continuity_test_'+uuid.uuid4().hex
    with engine.begin() as connection:connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
    isolated=create_engine(url,connect_args={'options':f'-csearch_path={schema} -cstatement_timeout=15000 -c lock_timeout=10000'})
    try:
        Base.metadata.create_all(isolated)
        with Session(isolated) as db:
            company=Company(name='Disposable control test');db.add(company);db.flush()
            project=Project(company_id=company.id,name='Control test',timezone='UTC');db.add(project);db.flush()
            lead=Lead(company_id=company.id,project_id=project.id,full_name='Fictional control lead',phone='+15550100001',source='manual',consent_status='granted');db.add(lead);db.flush()
            conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms',provider='telnyx',is_paused=True,pause_reason='Paused by user');db.add(conversation);db.flush()
            inbound=SalesMessage(conversation_id=conversation.id,channel='sms',direction='inbound',role='user',content='Show homes',status='received');db.add(inbound);db.flush();continuity.received(db,conversation,inbound)
            db.commit();ids=(company.id,conversation.id,inbound.id)
        yield isolated,ids
    finally:
        isolated.dispose()
        with engine.begin() as connection:connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()


def test_postgres_duplicate_resume_has_one_active_continuation(postgres_case):
    engine,(company_id,conversation_id,inbound_id)=postgres_case;barrier=Barrier(2)
    def resume(_):
        with Session(engine) as db:
            barrier.wait(timeout=10);set_conversation_action(db,company_id=company_id,conversation_id=conversation_id,action='resume')
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(resume,range(2)))
    with Session(engine) as db:
        jobs=db.query(SalesFollowUpJob).filter_by(kind='resume',status='pending').all()
        assert len(jobs)==1 and jobs[0].payload_json['input_message_ids']==[inbound_id]
        assert db.query(OutboundMessage).count()==db.query(Meeting).count()==0


def test_postgres_inbound_racing_resume_is_retained_in_one_current_input_set(postgres_case):
    engine,(company_id,conversation_id,original_id)=postgres_case;barrier=Barrier(2)
    def run(kind):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            if kind=='resume':set_conversation_action(db,company_id=company_id,conversation_id=conversation_id,action='resume')
            else:
                conversation=db.query(SalesConversation).filter_by(id=conversation_id).with_for_update().one()
                message=SalesMessage(conversation_id=conversation.id,channel='sms',direction='inbound',role='user',content='Send plans too',status='received');db.add(message);db.flush();continuity.received(db,conversation,message);db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['resume','inbound']))
    with Session(engine) as db:
        job=db.query(SalesFollowUpJob).filter_by(kind='resume',status='pending').one()
        assert len(job.payload_json['input_message_ids'])==2 and original_id in job.payload_json['input_message_ids']
        assert db.query(OutboundMessage).count()==0


def test_postgres_two_fifo_claimers_never_claim_two_turns_for_one_conversation(postgres_case):
    engine,(_,conversation_id,original_id)=postgres_case
    with Session(engine) as db:
        conversation=db.get(SalesConversation,conversation_id);conversation.is_paused=False
        for index in range(2):
            message=SalesMessage(conversation_id=conversation_id,channel='sms',direction='inbound',role='user',content=f'Question {index}',status='received');db.add(message);db.flush()
            db.add(SalesInboundJob(conversation_id=conversation_id,message_id=message.id,status='pending',created_at=datetime(2026,1,1,0,0,index)))
        db.commit()
    barrier=Barrier(2)
    def claim(_):barrier.wait(timeout=10);return live_worker._claim_inbound_jobs()
    with patch.object(live_worker,'SessionLocal',sessionmaker(bind=engine)):
        with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(claim,range(2)))
    assert sum(len(v) for v in claims)==1
