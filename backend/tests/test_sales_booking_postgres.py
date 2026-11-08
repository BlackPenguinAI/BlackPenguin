"""Optional actual PostgreSQL contention. Never run against a non-test database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from threading import Barrier
from types import SimpleNamespace
import os,uuid
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
import app.db.base
from app.db.postgres import Base
from app.modules.companies.models import Company
from app.modules.projects.models import Project,ProjectProfile,ProjectPropertyType
from app.modules.users.models import User,UserRole
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.sales_crm.models import Lead,Meeting,SalesAvailabilityBlock
from app.modules.governance.models import NotificationOutbox
from app.modules.sales_agent.models import SalesConversation,SalesMessage
from app.modules.sales_agent.booking_models import SalesBookingOperation
from app.modules.sales_agent.dialogue_store import Scope
from app.modules.sales_agent.understanding_contract import DialogueState,Task
from app.modules.sales_agent.first_booking import handle,context_snapshot,normalize_timing
from app.modules.sales_agent.turn_configuration import digest
from test_sales_active_integration import understanding


@pytest.mark.parametrize('same_lead',[False,True],ids=['two-leads-one-specialist','one-lead-two-channels'])
def test_postgres_first_booking_contention_has_one_reservation_and_one_effect(same_lead):
    url=os.environ.get('DIALOGUE_POSTGRES_TEST_URL')
    if not url:pytest.skip('Disposable PostgreSQL URL not supplied; SQLite is not a parallel-worker proof.')
    engine=create_engine(url)
    assert engine.dialect.name=='postgresql'
    with engine.connect() as connection:
        assert connection.execute(text('SELECT current_database()')).scalar_one().endswith('_test')
    schema='bp_booking_test_'+uuid.uuid4().hex
    with engine.begin() as connection:connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
    isolated=create_engine(url,connect_args={'options':f'-csearch_path={schema} -cstatement_timeout=15000'})
    try:
        Base.metadata.create_all(isolated)
        entries=[];starts=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
        with Session(isolated) as db:
            company=Company(name='Disposable booking fixture');db.add(company);db.flush()
            project=Project(company_id=company.id,name='Test property',address='100 Test St',timezone='UTC')
            project.profile=ProjectProfile(profile_data={},field_states={});db.add(project);db.flush()
            product=ProjectPropertyType(project=project,name='Studio',review_status='confirmed')
            sales=User(company_id=company.id,email='parallel@example.invalid',first_name='Parallel',last_name='Sales',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True)
            db.add_all([product,sales]);db.flush()
            db.add(ProjectUserAssignment(project_id=project.id,user_id=sales.id,responsibility='sales',sales_enabled=True,is_active=True,accepts_appointments=True))
            db.add(SalesAvailabilityBlock(user_id=sales.id,starts_at=starts,ends_at=starts+timedelta(hours=1),timezone='UTC'))
            first_lead=None
            for index in range(2):
                lead=first_lead if same_lead and first_lead else Lead(company_id=company.id,project_id=project.id,full_name='Fictional lead '+str(index),phone='+1555010000'+str(index),source='manual',consent_status='granted')
                if lead is not first_lead:db.add(lead);db.flush()
                first_lead=first_lead or lead
                conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,channel='sms' if index==0 or not same_lead else 'whatsapp',provider='telnyx',is_paused=False)
                db.add(conversation);db.flush()
                scope=Scope(company.id,project.id,conversation.id,lead.id)
                state=DialogueState(selected_property_type_id=product.id,booking_search={'property_type_id':product.id,'unit_id':None,'duration_minutes':45})
                context=context_snapshot(db,scope,project,state,{'label':'Primary location','address':project.address})
                prefs=normalize_timing(understanding('Yes','appointment'),'Yes',project,datetime.utcnow(),{})
                option={'starts_at':starts.replace(tzinfo=timezone.utc).isoformat(),'sales_user_id':sales.id,'specialist_name':'Parallel Sales'}
                proposal={'scope':scope.__dict__,'context':context,'preferences':prefs,'option':option,'offer_message_id':str(uuid.uuid4()),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()}
                proposal['id']=digest(proposal);state.booking_proposal=proposal
                message=SalesMessage(conversation_id=conversation.id,channel=conversation.channel,direction='outbound',role='assistant',status='delivered',content='Confirm this exact visit?',metadata_json={'booking_confirmation':{'id':proposal['id']}})
                db.add(message);db.flush()
                inbound=SalesMessage(conversation_id=conversation.id,channel=conversation.channel,direction='inbound',role='user',status='received',content='Yes')
                db.add(inbound);db.flush()
                state.last_understanding=understanding('Yes','appointment')
                state.tasks=[Task(id='booking',topic='appointment',status='pending',source_message_id=inbound.id,request_ids=['r0'])]
                entries.append((scope,inbound.id,state.model_dump(mode='json')))
            db.commit()
        barrier=Barrier(2)
        def reserve(entry):
            scope,message_id,state=entry
            with Session(isolated) as db:
                conversation=db.get(SalesConversation,scope.conversation_id);lead=db.get(Lead,scope.lead_id);project=db.get(Project,scope.project_id);inbound=db.get(SalesMessage,message_id)
                outcome=SimpleNamespace(state=DialogueState.model_validate(state),plan={'write_candidates_require_backend_authorization':['booking'],'references':{}})
                barrier.wait(timeout=10)
                result=handle(db,scope,conversation,lead,project,outcome,inbound)
                db.commit();return bool(result[1].get('meeting_id'))
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,entries))
        assert sorted(results)==[False,True]
        with Session(isolated) as db:
            assert db.query(Meeting).count()==db.query(SalesBookingOperation).count()==1
            assert db.query(NotificationOutbox).filter_by(event_type='appointment_confirmed').count()==1
    finally:
        isolated.dispose()
        with engine.begin() as connection:connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()
