"""First booking and post-booking continuity through the production coordinator."""
from datetime import datetime,timedelta,timezone
import asyncio,json
from unittest.mock import patch,AsyncMock
import pytest
from fastapi import HTTPException
from test_sales_turn_1720 import case,outbound
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product,inbound
from test_sales_ai_group_d import availability,typed,req,ref
from test_sales_active_integration import understanding
from app.core.config import settings
from app.modules.sales_agent.understanding_contract import Understanding,VisitTiming,VisitDirective
from app.modules.sales_agent.dialogue_store import load,save
from app.modules.sales_agent.models import SalesMessage,SalesFollowUpJob,AgentRun
from app.modules.sales_agent.booking_models import SalesBookingOperation
from app.modules.sales_agent.first_booking import normalize_timing,retry_calendars,sync_calendar
from app.modules.sales_crm.models import Meeting,CalendarConnection,MeetingStatus
from app.modules.governance.models import NotificationOutbox,Notification
from app.modules.governance.services import process_notification_outbox


def latest(agent):return agent.db.query(SalesMessage).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()


def visit(text,*,action='request',timing=None):
    u=understanding(text,'appointment')
    return Understanding.model_validate({**u.model_dump(),'visit':{'action':action,'evidence':text,'timing':timing}})


def courtesy(text,kind):
    return Understanding.model_validate({**understanding(text,'other').model_dump(),'courtesy':{'kind':kind,'evidence':text}})


def options(agent):
    starts=availability(agent);product(agent,'Studio')
    agent.turn('I want to arrange a visit',visit('I want to arrange a visit'))
    msg=latest(agent)
    assert msg.metadata_json.get('appointment_offer'),agent.db.query(AgentRun).all()[-1].output_snapshot
    return starts,msg.metadata_json['appointment_offer']


def select(agent):
    starts,offer=options(agent)
    text='1'
    _,run=agent.turn(text,typed(text,[req('slot','appointment',text,ref='s')],[ref('s','appointment',text)]))
    assert not agent.db.query(Meeting).count(),run.output_snapshot
    assert latest(agent).metadata_json.get('booking_confirmation'),run.output_snapshot
    return starts,offer


def book(agent):
    starts,offer=select(agent)
    message,run=agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).count()==1,run.output_snapshot
    return message,run,agent.db.query(Meeting).one(),starts


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_first_booking_is_two_step_complete_scoped_and_open(agent,channel):
    agent.conversation.channel=channel
    _,run,row,starts=book(agent)
    assert row.meeting_time==starts and row.visit_property_type_id and row.assigned_sales_user_id
    assert row.visit_address=='100 Main St' and row.visit_context['property_type_name']=='Studio'
    assert not agent.conversation.is_paused and agent.conversation.pause_reason is None
    text=latest(agent).content
    assert 'confirmed' in text and 'Studio' in text and 'Test Specialist' in text and '45 minutes' in text and 'UTC' in text and '100 Main St' in text
    assert latest(agent).channel==channel and text.count('?')==1
    assert agent.db.query(SalesBookingOperation).one().meeting_id==row.id
    assert agent.db.query(NotificationOutbox).filter_by(event_type='appointment_confirmed').count()==1
    assert load(agent.db,agent.scope)[1].cadence_stop_reason=='booked'


def test_booking_delivery_retry_reuses_receipt_and_does_not_book_again(agent):
    select(agent);agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(Meeting).one();op=agent.db.query(SalesBookingOperation).one()
    message=agent.db.query(SalesMessage).filter_by(direction='inbound',content='Yes').one();count=agent.infer.await_count
    agent.send.side_effect=lambda *a,**kw:{'sid':str(__import__('uuid').uuid4()),'status':'sent'}
    agent.retry(message)
    assert agent.db.query(Meeting).one().id==row.id and agent.db.query(SalesBookingOperation).one().id==op.id
    assert agent.infer.await_count==count
    agent.turn('Yes',understanding('Yes','appointment'))
    assert agent.db.query(Meeting).count()==1 and not agent.conversation.is_paused


def test_after_booking_queries_other_property_and_farewell_preserve_visit(agent):
    _,_,row,_=book(agent);before=(row.meeting_time,row.visit_property_type_id,row.visit_address)
    text='When is my appointment?'
    u=understanding(text,'appointment').model_copy(update={'appointment_query':'active'})
    agent.turn(text,u)
    assert 'Studio' in latest(agent).content and '100 Main St' in latest(agent).content
    product(agent,'Loft');text='Tell me about Loft'
    agent.turn(text,typed(text,[req('d','property_details',text,ref='p')],[ref('p','property','Loft')]))
    assert 'Loft' in latest(agent).content and agent.db.query(Meeting).count()==1
    agent.turn('Thanks, goodbye',courtesy('Thanks, goodbye','farewell'))
    assert 'budget' not in latest(agent).content and not agent.conversation.is_paused and not agent.lead.is_opt_out
    agent.turn('Hello again',courtesy('Hello again','greeting'))
    assert 'Welcome back' in latest(agent).content
    agent.db.refresh(row);assert (row.meeting_time,row.visit_property_type_id,row.visit_address)==before


def test_no_after_confirmation_question_is_farewell_not_cancel_or_opt_out(agent):
    book(agent)
    agent.turn('No, no more questions',courtesy('No, no more questions','farewell'))
    assert agent.db.query(Meeting).one().status==MeetingStatus.CONFIRMED
    assert not agent.lead.is_opt_out and not agent.conversation.is_paused


def test_declining_proposal_does_not_book_or_pause(agent):
    select(agent)
    agent.turn('No thanks',courtesy('No thanks','decline'))
    assert not agent.db.query(Meeting).count() and not load(agent.db,agent.scope)[1].booking_proposal
    assert not agent.conversation.is_paused and not agent.lead.is_opt_out


def test_farewell_stops_cadence_but_later_question_is_answered(agent):
    product(agent)
    job=SalesFollowUpJob(conversation_id=agent.conversation.id,status='pending',reason='warm_cadence',idempotency_key='test-farewell-cadence',scheduled_at=datetime.utcnow())
    agent.db.add(job);agent.db.commit()
    agent.turn('Goodbye',courtesy('Goodbye','farewell'))
    agent.db.refresh(job);assert job.status=='cancelled' and not agent.conversation.is_paused
    agent.turn('Give me information',understanding('Give me information','catalog'))
    assert 'Studio' in latest(agent).content and not agent.conversation.is_paused
    from app.modules.sales_agent.live_service import _schedule_next_action
    _schedule_next_action(agent.db,agent.conversation,agent.lead,'test',refresh_pending=True)
    assert not agent.db.query(SalesFollowUpJob).filter_by(status='pending').count()


@pytest.mark.parametrize('kind',['property','manual','incomplete','expired'])
def test_confirmation_cannot_use_an_unrelated_or_incomplete_offer(agent,kind):
    select(agent)
    if kind=='property':outbound(agent.db,agent.conversation,'Review the property',{'property_catalog_offer':{'property_type_ids':[load(agent.db,agent.scope)[1].selected_property_type_id]}})
    elif kind=='manual':
        row=outbound(agent.db,agent.conversation,'Human message');row.role='human';agent.db.commit()
    elif kind=='incomplete':
        row=latest(agent);row.metadata_json={**row.metadata_json,'delivery_group':{'key':'partial','part':1,'total':2}};agent.db.commit()
    elif kind=='expired':
        revision,state=load(agent.db,agent.scope);state.booking_proposal={**state.booking_proposal,'expires_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}
        save(agent.db,agent.scope,event_key='expire',expected_revision=revision,state=state);agent.db.commit()
    agent.turn('Yes',understanding('Yes','appointment'))
    assert not agent.db.query(Meeting).count() and not agent.conversation.is_paused


@pytest.mark.parametrize('change',['specialist','location','duration_conflict','property'])
def test_proposal_details_are_revalidated_before_booking(agent,change):
    starts,offer=select(agent)
    if change=='specialist':
        from app.modules.users.models import User
        user=agent.db.get(User,offer['options'][0]['sales_user_id']);user.is_active=False
    elif change=='location':agent.project.address='Changed location'
    elif change=='property':
        p=agent.db.query(__import__('app.modules.projects.models',fromlist=['ProjectPropertyType']).ProjectPropertyType).one();p.review_status='pending'
    else:
        from test_sales_ai_group_c import meeting
        meeting(agent,starts=starts);other=agent.db.query(Meeting).one();other.assigned_sales_user_id=offer['options'][0]['sales_user_id'];other.lead_id=__import__('uuid').uuid4().hex
    agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesBookingOperation).count() and not agent.conversation.is_paused


def test_structured_temporal_preferences_are_normalized_and_applied(agent):
    starts=availability(agent);product(agent)
    day=starts.strftime('%Y-%m-%d');text=f'Book a visit on {day} after 3:30 PM for 30 minutes in UTC'
    timing={'date_from_evidence':day,'time_from_evidence':'3:30 PM','time_relation':'after','duration_evidence':'30 minutes','timezone_evidence':'UTC'}
    agent.turn(text,visit(text,timing=timing))
    offer=latest(agent).metadata_json['appointment_offer']
    assert offer['duration_minutes']==30 and offer['preferences']['time_from']=='15:30'
    assert all(datetime.fromisoformat(o['starts_at']).hour>=15 and datetime.fromisoformat(o['starts_at']).minute>=0 for o in offer['options'])
    assert min(datetime.fromisoformat(o['starts_at']) for o in offer['options']).replace(tzinfo=None)>=starts+timedelta(minutes=30)


def test_multiple_properties_are_resolved_before_offering_a_visit(agent):
    availability(agent);product(agent,'Studio');loft=product(agent,'Loft')
    agent.turn('I want a visit',visit('I want a visit'))
    assert latest(agent).metadata_json.get('booking_property_question')
    text='Loft';agent.turn(text,typed(text,[req('p','property_details',text,ref='p')],[ref('p','property',text)]))
    assert latest(agent).metadata_json.get('appointment_offer')
    assert latest(agent).metadata_json['appointment_offer']['property_type_id']==loft.id


def test_calendar_failure_is_durable_and_does_not_rollback_or_duplicate_booking(agent):
    select(agent)
    offer=load(agent.db,agent.scope)[1].booking_proposal
    connection=CalendarConnection(user_id=offer['option']['sales_user_id'],provider='google',status='connected',calendar_id='offline')
    agent.db.add(connection);agent.db.commit()
    with patch('app.modules.sales_crm.scheduling.is_calendar_free',return_value=True),patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=RuntimeError('offline')):
        agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(Meeting).one();op=agent.db.query(SalesBookingOperation).one()
    assert row.calendar_sync_status=='failed' and op.calendar_status=='retry' and op.calendar_attempts==1
    op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'deterministic-calendar'}) as create:
        retry_calendars(agent.db)
        assert create.call_args.kwargs['event_id']=='bp'+row.id.replace('-','')
        retry_calendars(agent.db)
        assert create.call_count==1
    assert agent.db.query(Meeting).count()==1 and agent.db.query(SalesBookingOperation).one().calendar_status=='synced'


def test_notifications_are_durable_and_idempotent(agent):
    book(agent)
    process_notification_outbox(agent.db);before=agent.db.query(Notification).count()
    process_notification_outbox(agent.db)
    assert before>0 and agent.db.query(Notification).count()==before


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_real_provider_ingress_recovers_only_system_booking_pause_and_deduplicates(agent,channel):
    from fastapi import BackgroundTasks
    from app.modules.sales_agent.provider_router import _record_inbound
    from app.modules.sales_agent.models import SalesInboundJob
    from test_sales_ai_group_c import meeting
    row=meeting(agent);row.source='agent_sms_active'
    agent.conversation.channel=channel;agent.conversation.is_paused=True;agent.conversation.pause_reason='Appointment confirmed'
    agent.lead.agent_status='appointment_confirmed';agent.db.commit()
    kwargs=dict(provider='telnyx',event_id='f-ingress-'+channel,to_number='+15550100002',from_number=agent.lead.phone,
        body='When is my appointment?',payload={},background_tasks=BackgroundTasks(),expected_company_id=agent.company.id,channel=channel)
    with patch('app.modules.sales_agent.provider_router.resolve_inbound_conversation',return_value=agent.conversation):
        _record_inbound(agent.db,**kwargs);_record_inbound(agent.db,**kwargs)
    assert not agent.conversation.is_paused and agent.db.query(SalesInboundJob).count()==1
    msg=agent.db.query(SalesMessage).filter_by(direction='inbound').one()
    u=understanding(msg.content,'appointment').model_copy(update={'appointment_query':'active'})
    agent.infer.return_value=u.model_dump_json()
    with agent.patched():
        from app.modules.sales_agent.live_service import process_live_inbound
        asyncio.run(process_live_inbound(agent.conversation.id,msg.id))
    assert '100 Main Street' in latest(agent).content and agent.db.query(Meeting).one().id==row.id


@pytest.mark.parametrize('reason',['Manual pause','Human intervention: review','Lead opted out'])
def test_ingress_does_not_lift_manual_security_or_opt_out_pauses(agent,reason):
    from fastapi import BackgroundTasks
    from app.modules.sales_agent.provider_router import _record_inbound
    from app.modules.sales_agent.models import SalesInboundJob
    from test_sales_ai_group_c import meeting
    meeting(agent);agent.conversation.is_paused=True;agent.conversation.pause_reason=reason;agent.db.commit()
    with patch('app.modules.sales_agent.provider_router.resolve_inbound_conversation',return_value=agent.conversation):
        _record_inbound(agent.db,provider='telnyx',event_id='held',to_number='+15550100002',from_number=agent.lead.phone,
            body='Hello',payload={},background_tasks=BackgroundTasks(),expected_company_id=agent.company.id)
    assert agent.conversation.is_paused and not agent.db.query(SalesInboundJob).count()


def test_coordinator_recovers_legacy_booking_pause_without_webhook(agent):
    from test_sales_ai_group_c import meeting
    row=meeting(agent);row.source='agent_sms_active'
    agent.conversation.is_paused=True;agent.conversation.pause_reason='Appointment confirmed';agent.lead.agent_status='appointment_confirmed';agent.db.commit()
    agent.turn('Hello again',courtesy('Hello again','greeting'))
    assert not agent.conversation.is_paused and 'Welcome back' in latest(agent).content
    assert load(agent.db,agent.scope)[1].cadence_stop_reason=='booked'


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_booking_cadence_is_cancelled_and_claimed_old_job_never_sends(agent,channel):
    from app.modules.sales_agent import live_service as live
    agent.conversation.channel=channel
    book(agent)
    job=SalesFollowUpJob(conversation_id=agent.conversation.id,status='processing',reason='warm_cadence',
        idempotency_key='old-cadence',scheduled_at=datetime.utcnow())
    agent.db.add(job);agent.db.commit();before=agent.send.await_count
    with agent.patched():asyncio.run(live.process_live_followup_job(job.id))
    agent.db.refresh(job)
    assert job.status=='cancelled' and agent.send.await_count==before


def test_no_qualified_sales_asks_alert_permission_without_creating_wait(agent):
    product(agent)
    agent.turn('Arrange a visit',visit('Arrange a visit'))
    assert not agent.db.query(Meeting).count() and 'could not find a verified time' in latest(agent).content
    from app.modules.sales_agent.wait_models import SalesWaitRequest
    assert not agent.db.query(SalesWaitRequest).count() and not agent.conversation.is_paused
    assert latest(agent).metadata_json.get('wait_offer') and 'Would you like me to save a request' in latest(agent).content
    assert 'I will notify' not in latest(agent).content
    assert load(agent.db,agent.scope)[1].booking_search


def test_timing_evidence_validation_rejects_invented_substrings():
    with pytest.raises(ValueError):
        visit('Book tomorrow',timing={'date_from_evidence':'next Friday'}) .check_evidence('Book tomorrow')


@pytest.mark.parametrize('timing,text',[
    ({'timezone_evidence':'Mars/Olympus'},'Book in Mars/Olympus'),
    ({'duration_evidence':'999 minutes'},'Book for 999 minutes'),
    ({'time_relation':'afternoon'},'Book a visit'),
    ({'date_from_evidence':'not a date'},'Book on not a date'),
    ({'time_relation':'range','time_from_evidence':'5:00 PM','time_until_evidence':'3:00 PM'},'Book between 5:00 PM and 3:00 PM'),
])
def test_invalid_temporal_preferences_ask_without_booking(agent,timing,text):
    availability(agent);product(agent)
    agent.turn(text,visit(text,timing=timing))
    assert not agent.db.query(Meeting).count() and not latest(agent).metadata_json.get('appointment_offer')
    assert not agent.conversation.is_paused


def test_explicit_timezone_converts_time_correctly(agent):
    starts=availability(agent);product(agent)
    local=starts.replace(tzinfo=timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/Lima'))
    day=local.strftime('%Y-%m-%d');clock=local.strftime('%I:%M %p')
    text=f'Book {day} at {clock} in America/Lima'
    agent.turn(text,visit(text,timing={'date_from_evidence':day,'time_from_evidence':clock,'time_relation':'exact','timezone_evidence':'America/Lima'}))
    offer=latest(agent).metadata_json['appointment_offer']
    assert datetime.fromisoformat(offer['options'][0]['starts_at']).replace(tzinfo=None)==starts
    agent.turn('1',typed('1',[req('a','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'))
    assert 'America/Lima' in latest(agent).content and agent.db.query(Meeting).one().meeting_time==starts


def test_unit_and_location_details_are_pinned_in_first_booking(agent):
    from app.modules.projects.models import ProjectUnit
    availability(agent);p=product(agent,'Studio')
    unit=ProjectUnit(project=agent.project,unit_code='S-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow())
    agent.db.add(unit);agent.db.commit()
    text='Arrange a visit to S-101'
    agent.turn(text,typed(text,[req('a','appointment',text,ref='u')],[ref('u','unit','S-101')]))
    agent.turn('1',typed('1',[req('a','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(Meeting).one()
    assert row.visit_unit_id==unit.id and row.visit_property_type_id==p.id and 'S-101' in latest(agent).content


def test_multiple_locations_require_current_location_choice(agent):
    availability(agent);product(agent)
    agent.project.profile.profile_data={'exact_address':[{'label':'Office','address':'100 Office St'},{'label':'Showroom','address':'200 Showroom St'}]}
    agent.project.profile.field_states={'exact_address':{'status':'confirmed','applicable':True}};agent.db.commit()
    agent.turn('Arrange a visit',visit('Arrange a visit'))
    assert latest(agent).metadata_json.get('location_offer')
    text='Showroom';agent.turn(text,typed(text,[req('a','appointment',text,ref='l')],[ref('l','location','Showroom')]))
    assert latest(agent).metadata_json['appointment_offer']['context']['location']['address']=='200 Showroom St'
    agent.turn('1',typed('1',[req('a','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).one().visit_address=='200 Showroom St'


def test_new_migration_roundtrip_preserves_existing_meetings():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    file=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_booking_operations.py'
    spec=importlib.util.spec_from_file_location('booking_migration',file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        for table in ['companies','projects','sales_conversations','leads']:conn.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, visit_address TEXT)'))
        conn.execute(text("INSERT INTO meetings VALUES ('old', 'Original address')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade();assert 'sales_booking_operations' in inspect(conn).get_table_names()
            assert conn.execute(text('SELECT count(*) FROM sales_booking_operations')).scalar()==0
            module.downgrade();assert 'sales_booking_operations' not in inspect(conn).get_table_names()
            assert conn.execute(text('SELECT visit_address FROM meetings')).scalar()=='Original address'
            module.upgrade()
    engine.dispose()


@pytest.mark.parametrize('reply',['No','No thanks','No, no more questions'])
def test_bare_contextual_no_after_booking_cannot_become_opt_out_or_cancel(agent,reply):
    book(agent)
    agent.turn(reply,understanding(reply,'opt_out'))
    assert agent.db.query(Meeting).one().status==MeetingStatus.CONFIRMED
    assert not agent.conversation.is_paused and not agent.lead.is_opt_out
    assert 'stop all messages' not in latest(agent).content


def test_bare_no_declines_the_exact_booking_question_despite_bad_model_label(agent):
    select(agent)
    agent.turn('No',understanding('No','appointment'))
    assert not agent.db.query(Meeting).count() and not load(agent.db,agent.scope)[1].booking_proposal
    assert not agent.conversation.is_paused


def test_confirmation_with_independent_photos_keeps_true_booking_and_one_question(agent):
    from test_sales_turn_1720 import approved_asset
    select(agent)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    text='Yes, and send photos'
    u=understanding(text,'appointment','materials',subjects={1:'photos'})
    u=Understanding.model_validate({**u.model_dump(),'visit':{'action':'confirm','evidence':'Yes','timing':None}})
    agent.turn(text,u)
    assert agent.db.query(Meeting).count()==1 and 'Your visit is confirmed' in latest(agent).content
    assert 'remains pending' not in latest(agent).content and latest(agent).content.count('?')==1
    assert latest(agent).metadata_json.get('material_offer')


def test_calendar_retries_stop_at_review_without_new_meetings(agent):
    select(agent);proposal=load(agent.db,agent.scope)[1].booking_proposal
    agent.db.add(CalendarConnection(user_id=proposal['option']['sales_user_id'],provider='google',status='connected'));agent.db.commit()
    with patch('app.modules.sales_crm.scheduling.is_calendar_free',return_value=True),patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=RuntimeError('offline')) as create:
        agent.turn('Yes',understanding('Yes','other'))
        op=agent.db.query(SalesBookingOperation).one()
        for _ in range(8):
            op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit();retry_calendars(agent.db)
        assert create.call_count==5 and op.calendar_status=='review'
    assert agent.db.query(Meeting).count()==1


def test_notification_failure_after_booking_can_be_retried(agent):
    book(agent)
    event=agent.db.query(NotificationOutbox).filter_by(event_type='appointment_confirmed').one()
    with patch.object(agent.db,'commit',side_effect=RuntimeError('offline')):
        with pytest.raises(RuntimeError):process_notification_outbox(agent.db)
    agent.db.rollback()
    assert agent.db.get(NotificationOutbox,event.id).status=='pending'
    process_notification_outbox(agent.db)
    assert agent.db.get(NotificationOutbox,event.id).status=='processed' and agent.db.query(Meeting).count()==1


def test_open_human_case_prevents_legacy_pause_recovery(agent):
    from test_sales_ai_group_c import meeting
    from app.modules.governance.services import create_intervention_case
    from app.modules.sales_agent.first_booking import recover_booking_pause
    meeting(agent)
    create_intervention_case(agent.db,conversation=agent.conversation,lead=agent.lead,reason='HUMAN_REQUESTED',evidence='Speak to Sales')
    agent.conversation.is_paused=True;agent.conversation.pause_reason='Appointment confirmed';agent.db.commit()
    assert not recover_booking_pause(agent.db,agent.conversation) and agent.conversation.is_paused


def test_courtesy_state_survives_restart_and_does_not_start_new_appointment(agent):
    agent.turn('Goodbye',courtesy('Goodbye','farewell'))
    agent.db.expire_all()
    assert load(agent.db,agent.scope)[1].cadence_status=='stopped'
    agent.turn('Hello',courtesy('Hello','greeting'))
    assert 'Welcome back' in latest(agent).content and not agent.db.query(Meeting).count()


def test_sales_notice_targets_booked_specialist_even_if_lead_is_reassigned(agent):
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    book(agent);old=agent.db.query(Meeting).one().assigned_sales_user_id
    other=User(company_id=agent.company.id,email='other-sales@example.invalid',first_name='Other',last_name='Sales',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True)
    agent.db.add(other);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=agent.project.id,user_id=other.id,responsibility='sales',sales_enabled=True,is_active=True))
    agent.lead.assigned_sales_user_id=other.id;agent.db.commit()
    process_notification_outbox(agent.db)
    assert agent.db.query(Notification).filter_by(recipient_user_id=old,notification_type='appointment_confirmed').count()==1
    assert not agent.db.query(Notification).filter_by(recipient_user_id=other.id,notification_type='appointment_confirmed').count()


def test_changed_booking_is_not_silently_synced_as_the_old_operation(agent):
    _,_,row,_=book(agent);op=agent.db.query(SalesBookingOperation).one()
    row.meeting_time+=timedelta(days=1);agent.db.commit()
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection') as create:
        sync_calendar(agent.db,op.id)
        create.assert_not_called()
    assert op.calendar_status=='review' and op.last_error=='BookingChanged'


def test_running_visit_blocks_overlapping_specialist_slot(agent):
    from app.modules.sales_crm.scheduling import eligible_users_for_slot
    starts,offer=options(agent);uid=offer['options'][0]['sales_user_id']
    from test_sales_ai_group_c import meeting
    row=meeting(agent,starts=starts-timedelta(minutes=15),status=MeetingStatus.IN_PROGRESS)
    row.assigned_sales_user_id=uid;row.duration_minutes=90;agent.db.commit()
    assert not eligible_users_for_slot(agent.db,project_id=agent.project.id,starts_at=starts,duration_minutes=45)


@pytest.mark.parametrize('channel',['sms','whatsapp'])
@pytest.mark.parametrize('index',range(6))
def test_six_exported_projects_keep_first_visit_requests_scoped_and_no_unconfirmed_booking(index,channel,monkeypatch):
    from sales_ai_support.sandbox import Sandbox,InboundHarness,load_catalog
    catalog=load_catalog();sandbox=Sandbox(catalog)
    try:
        pid=catalog['projects'][index]['project']['id'];text='I would like to arrange a visit'
        h=InboundHarness(sandbox,pid,channel,monkeypatch,visit(text))
        monkeypatch.setattr(settings,'SALES_NEXT_FLOW_ENABLED',True);monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS',pid)
        _,run=h.turn(text)
        assert run.status=='completed' and not h.conversation.is_paused,run.output_snapshot
        assert not h.db.query(Meeting).count() and not h.calendar.calls
        offer=run.output_snapshot['metadata'].get('appointment_offer')
        if offer:
            assert offer['version']=='sales-first-booking/1.0' and offer['context']['project_id']==pid
            assert all(o['sales_user_id'] for o in offer['options'])
        assert not run.output_snapshot['metadata'].get('language_hold')
    finally:sandbox.close()


def test_two_leads_with_same_offered_time_cannot_both_confirm(agent):
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    from app.modules.sales_agent.dialogue_store import Scope
    from app.modules.sales_agent.first_booking import handle
    from types import SimpleNamespace
    starts,offer=select(agent)
    original=load(agent.db,agent.scope)[1].booking_proposal
    other=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other lead',phone='+15550100002',source='manual',consent_status='granted')
    agent.db.add(other);agent.db.flush()
    conv=SalesConversation(company_id=agent.company.id,project_id=agent.project.id,lead_id=other.id,channel='sms',provider='telnyx',is_paused=False)
    agent.db.add(conv);agent.db.flush();scope=Scope(agent.company.id,agent.project.id,conv.id,other.id)
    from app.modules.sales_agent.turn_configuration import digest
    from app.modules.sales_agent.understanding_contract import DialogueState,Task
    proposal={**original,'scope':scope.__dict__};proposal.pop('id');proposal['id']=digest(proposal)
    outbound(agent.db,conv,'Confirm the visit?',{'booking_confirmation':{'id':proposal['id']}})
    other_inbound=SalesMessage(conversation_id=conv.id,channel='sms',direction='inbound',role='user',content='Yes',status='received');agent.db.add(other_inbound);agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    state=DialogueState(booking_proposal=proposal,booking_search={'property_type_id':proposal['context']['property_type_id'],'unit_id':None,'duration_minutes':45},last_understanding=understanding('Yes','appointment'),tasks=[Task(id='booking',topic='appointment',status='pending',source_message_id=other_inbound.id)])
    result=handle(agent.db,scope,conv,other,agent.project,SimpleNamespace(state=state,plan={'write_candidates_require_backend_authorization':['booking'],'references':{}}),other_inbound)
    assert not result[1].get('meeting_id') and 'no longer available' in result[0]
    agent.db.commit();assert agent.db.query(Meeting).count()==1


def test_explicit_suspended_time_reference_prepares_summary_without_renewing_expiry(agent):
    from test_sales_turn_1720 import approved_asset
    starts,offer=options(agent)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan'])
    agent.turn('Send floor plans first',understanding('Send floor plans first','materials',subjects={0:'floor_plan'}))
    text='3:00 PM'
    agent.turn(text,typed(text,[req('a','appointment',text,ref='s')],[ref('s','appointment',text)]))
    assert latest(agent).metadata_json.get('booking_confirmation')
    assert load(agent.db,agent.scope)[1].booking_proposal['expires_at']==offer['expires_at']
    assert not agent.db.query(Meeting).count()


def test_booking_migration_generates_postgres_sql_without_touching_data():
    import importlib.util,io
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_booking_operations.py'
    spec=importlib.util.spec_from_file_location('booking_sql',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})):
        module.upgrade()
    sql=output.getvalue()
    assert 'CREATE TABLE sales_booking_operations' in sql and 'UNIQUE (proposal_id)' in sql and 'UNIQUE (meeting_id)' in sql
    assert 'UPDATE meetings' not in sql and 'DELETE' not in sql.replace('ON DELETE CASCADE','')


def test_property_question_interrupted_by_photos_does_not_start_scheduling(agent):
    from test_sales_turn_1720 import approved_asset
    availability(agent);product(agent,'Studio');loft=product(agent,'Loft')
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['gallery_image']);asset.property_type_id=loft.id;agent.db.commit()
    agent.turn('I want a visit',visit('I want a visit'))
    text='Send Loft photos first'
    agent.turn(text,typed(text,[req('m','materials',text,ref='p',subject='photos')],[ref('p','property','Loft')]))
    assert not latest(agent).metadata_json.get('appointment_offer') and not agent.db.query(Meeting).count()
    assert '/projects/a/' in latest(agent).content


def test_explicit_decline_of_pending_proposal_never_cancels_an_existing_visit(agent):
    select(agent)
    text="I don't want this visit"
    agent.turn(text,visit(text,action='decline'))
    assert not agent.db.query(Meeting).count() and not load(agent.db,agent.scope)[1].booking_proposal
    assert 'No visit has been booked' in latest(agent).content


def test_incomplete_historical_effects_are_reviewed_without_starving_calendar_queue(agent):
    from app.modules.projects.models import Project
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    _,_,row,_=book(agent);op=agent.db.query(SalesBookingOperation).one()
    agent.db.add(CalendarConnection(user_id=row.assigned_sales_user_id,provider='google',status='connected'))
    op.calendar_status='pending';op.next_attempt_at=datetime.utcnow()-timedelta(minutes=1)
    disabled=Project(company_id=agent.company.id,name='Disabled scope',address='200 Test St',timezone='UTC');agent.db.add(disabled);agent.db.flush()
    lead=Lead(company_id=agent.company.id,project_id=disabled.id,full_name='Other lead',phone='+15550100003',source='manual',consent_status='granted');agent.db.add(lead);agent.db.flush()
    conv=SalesConversation(company_id=agent.company.id,project_id=disabled.id,lead_id=lead.id,channel='sms',provider='telnyx',is_paused=False);agent.db.add(conv);agent.db.flush()
    for index in range(11):
        meeting=Meeting(project_id=disabled.id,lead_id=lead.id,meeting_time=row.meeting_time,status=MeetingStatus.CONFIRMED);agent.db.add(meeting);agent.db.flush()
        agent.db.add(SalesBookingOperation(company_id=agent.company.id,project_id=disabled.id,lead_id=lead.id,conversation_id=conv.id,
            proposal_id='disabled-'+str(index),meeting_id=meeting.id,snapshot_json={},calendar_status='pending',next_attempt_at=datetime.utcnow()-timedelta(minutes=2)))
    agent.db.commit()
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'enabled-calendar'}) as create:
        retry_calendars(agent.db,limit=10)
        retry_calendars(agent.db,limit=10)
        assert create.call_count==1
    assert op.calendar_status=='synced'
