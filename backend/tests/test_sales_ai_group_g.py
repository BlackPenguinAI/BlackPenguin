"""Transactional rescheduling with the production coordinator, state and dispatcher."""
import asyncio,json,uuid
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,AsyncMock,Mock
import pytest
from test_sales_turn_1720 import case,outbound
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product,meeting
from test_sales_ai_group_f import book,latest,visit,options,courtesy
from test_sales_ai_group_d import typed,req,ref,availability
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.dialogue_store import load,save
from app.modules.sales_agent.models import SalesMessage,AgentRun
from app.modules.sales_agent.booking_models import SalesBookingOperation
from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
from app.modules.sales_crm.models import Meeting,MeetingStatus,CalendarConnection
from app.modules.governance.models import NotificationOutbox,Notification
from app.modules.governance.services import process_notification_outbox


def change(text,**fields):
    return Understanding.model_validate({**understanding(text,'appointment').model_dump(),
        'reschedule':{'action':'request','evidence':text,**fields}})


def prepare(agent,**fields):
    _,_,old,_=book(agent)
    text=fields.pop('text','I want to reschedule my visit')
    msg,run=agent.turn(text,change(text,**fields))
    assert latest(agent).metadata_json.get('reschedule_offer'),run.output_snapshot
    agent.turn('1',typed('1',[req('pick','appointment','1',ref='s')],[ref('s','appointment','1')]))
    assert latest(agent).metadata_json.get('reschedule_confirmation'),agent.db.query(AgentRun).all()[-1].output_snapshot
    return old


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_exact_comparison_then_atomic_replacement_keeps_chat_and_scope(agent,channel):
    agent.conversation.channel=channel;old=prepare(agent);previous_time=old.meeting_time;old_id=old.id
    assert agent.db.query(Meeting).count()==1 and old.status==MeetingStatus.CONFIRMED
    assert 'Current visit:' in latest(agent).content and 'Proposed replacement:' in latest(agent).content
    assert latest(agent).content.count('?')==1
    _,run=agent.turn('Yes',understanding('Yes','other'))
    assert run.status=='completed',run.output_snapshot
    op=agent.db.query(SalesRescheduleOperation).one();new=agent.db.get(Meeting,op.replacement_meeting_id);agent.db.refresh(old)
    assert old.id==old_id and old.meeting_time==previous_time and old.status==MeetingStatus.CANCELLED and old.confirmation_status=='rescheduled'
    assert new.status==MeetingStatus.CONFIRMED and new.id!=old.id and new.meeting_time!=old.meeting_time
    assert 'Your visit has been rescheduled' in latest(agent).content and 'Previous visit:' in latest(agent).content
    assert not agent.conversation.is_paused and agent.conversation.project_id==agent.project.id
    assert agent.db.query(NotificationOutbox).filter_by(event_type='appointment_rescheduled').count()==2


def test_decline_and_new_yes_preserve_original(agent):
    old=prepare(agent);when=old.meeting_time
    agent.turn('No',understanding('No','opt_out'))
    assert agent.db.query(Meeting).count()==1 and old.status==MeetingStatus.CONFIRMED
    assert not load(agent.db,agent.scope)[1].reschedule_proposal and not agent.lead.is_opt_out
    agent.turn('Yes',understanding('Yes','appointment'))
    assert agent.db.query(Meeting).count()==1 and agent.db.get(Meeting,old.id).meeting_time==when


def test_expiry_preserves_original(agent):
    old=prepare(agent)
    revision,state=load(agent.db,agent.scope)
    from app.modules.sales_agent.turn_configuration import digest
    p={**state.reschedule_proposal,'expires_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()};p.pop('id');p['id']=digest(p)
    state.reschedule_proposal=p
    save(agent.db,agent.scope,event_key='expire-reschedule',expected_revision=revision,state=state);agent.db.commit()
    row=latest(agent);row.metadata_json={**row.metadata_json,'reschedule_confirmation':{'id':p['id']}};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED and not agent.db.query(SalesRescheduleOperation).count()
    assert 'expired' in latest(agent).content


def test_changed_original_is_not_overwritten(agent):
    old=prepare(agent);old.meeting_time+=timedelta(days=1);agent.db.commit();when=old.meeting_time
    agent.turn('Yes',understanding('Yes','other'))
    agent.db.refresh(old)
    assert old.meeting_time==when and old.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesRescheduleOperation).count()


def test_late_conflict_preserves_original_and_routing(agent):
    from app.modules.sales_crm.models import Lead
    from app.modules.project_team.models import ProjectRoutingState
    old=prepare(agent);p=load(agent.db,agent.scope)[1].reschedule_proposal
    other=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other lead',phone='+15550100003',source='manual');agent.db.add(other);agent.db.flush()
    conflict=Meeting(project_id=agent.project.id,lead_id=other.id,assigned_sales_user_id=p['option']['sales_user_id'],
        meeting_time=datetime.fromisoformat(p['option']['starts_at']).replace(tzinfo=None),duration_minutes=45,status=MeetingStatus.CONFIRMED)
    agent.db.add(conflict);agent.db.commit();cursor=agent.db.query(ProjectRoutingState).one();before=cursor.assignment_sequence
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED and not agent.db.query(SalesRescheduleOperation).count()
    agent.db.refresh(cursor);assert cursor.assignment_sequence==before
    assert 'original reservation is unchanged' in latest(agent).content


def test_failed_delivery_and_double_confirmation_do_not_replace_twice(agent):
    old=prepare(agent);agent.send.side_effect=RuntimeError('offline')
    with pytest.raises(RuntimeError):agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();new_id=op.replacement_meeting_id
    msg=agent.db.query(SalesMessage).filter_by(direction='inbound',content='Yes').order_by(SalesMessage.created_at.desc()).first()
    count=agent.infer.await_count;agent.send.side_effect=lambda *a,**kw:{'sid':str(uuid.uuid4()),'status':'sent'}
    agent.retry(msg)
    assert agent.infer.await_count==count and agent.db.query(SalesRescheduleOperation).one().replacement_meeting_id==new_id
    agent.turn('Yes',understanding('Yes','appointment'))
    assert agent.db.query(SalesRescheduleOperation).count()==1 and agent.db.query(Meeting).count()==2


@pytest.mark.parametrize('kind',['manual','incomplete','unrelated'])
def test_acceptance_requires_the_exact_complete_current_comparison(agent,kind):
    old=prepare(agent)
    if kind=='manual':
        row=outbound(agent.db,agent.conversation,'Human reply');row.role='human';agent.db.commit()
    elif kind=='incomplete':
        row=latest(agent);row.metadata_json={**row.metadata_json,'delivery_group':{'key':'partial','part':1,'total':2}};agent.db.commit()
    else:outbound(agent.db,agent.conversation,'Any property questions?')
    agent.turn('Yes',understanding('Yes','appointment'))
    assert agent.db.query(Meeting).count()==1 and agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED


def test_new_property_is_explicitly_bound_and_interest_change_alone_does_not_move_booking(agent):
    _,_,old,_=book(agent);loft=product(agent,'Loft')
    text='Tell me about Loft';agent.turn(text,typed(text,[req('d','property_details',text,ref='p')],[ref('p','property','Loft')]))
    agent.turn('I want to reschedule my visit',change('I want to reschedule my visit'))
    assert latest(agent).metadata_json['reschedule_offer']['target_context']['property_type_id']==old.visit_property_type_id
    text='Move my visit to Loft'
    agent.turn(text,change(text,target_property='Loft'))
    agent.turn('1',typed('1',[req('p','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();assert agent.db.get(Meeting,op.replacement_meeting_id).visit_property_type_id==loft.id


def target_project(agent,name='Other Project',*,enabled=True,approved=True):
    from app.modules.projects.models import Project,ProjectProfile,ProjectPropertyType
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    from app.modules.users.models import User,UserRole
    from app.core.config import settings
    p=Project(company_id=agent.company.id,name=name,address='200 Target St',timezone='America/Chicago')
    p.profile=ProjectProfile(profile_data={},field_states={},final_approved=approved)
    agent.db.add(p);agent.db.flush()
    kind=ProjectPropertyType(project=p,name='Target Loft',review_status='confirmed')
    user=User(company_id=agent.company.id,email=str(uuid.uuid4())+'@example.invalid',first_name='Target',last_name='Specialist',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True)
    agent.db.add_all([kind,user]);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=p.id,user_id=user.id,responsibility='sales',sales_enabled=True,accepts_appointments=True,is_active=True))
    starts=(datetime.utcnow()+timedelta(days=3)).replace(hour=16,minute=0,second=0,microsecond=0)
    agent.db.add(SalesAvailabilityBlock(user_id=user.id,starts_at=starts,ends_at=starts+timedelta(hours=2),timezone='UTC'))
    if enabled:
        agent.config.agent_ventas={**agent.config.agent_ventas,'runtime_config':{**agent.config.agent_ventas['runtime_config'],'project_ids':[agent.project.id,p.id]}}
        settings.SALES_NEXT_FLOW_PROJECT_IDS=agent.project.id+','+p.id
    agent.db.commit();return p,kind,user


def request_and_choose(agent,text='I want to reschedule my visit',**fields):
    _,run=agent.turn(text,change(text,**fields))
    assert latest(agent).metadata_json.get('reschedule_offer'),run.output_snapshot
    agent.turn('1',typed('1',[req('p','appointment','1',ref='s')],[ref('s','appointment','1')]))
    assert latest(agent).metadata_json.get('reschedule_confirmation')


def test_cross_project_replacement_is_explicit_and_does_not_transfer_the_opportunity(agent):
    _,_,old,_=book(agent);original_lead_project=agent.lead.project_id;original_conv_project=agent.conversation.project_id
    target,kind,user=target_project(agent)
    text='Move my visit to Other Project with Target Specialist'
    request_and_choose(agent,text,target_project='Other Project',target_specialist='Target Specialist')
    proposal=load(agent.db,agent.scope)[1].reschedule_proposal
    assert proposal['target_context']['project_id']==target.id and 'Other Project' in latest(agent).content
    agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();new=agent.db.get(Meeting,op.replacement_meeting_id)
    assert new.project_id==target.id and new.visit_property_type_id==kind.id and new.assigned_sales_user_id==user.id
    assert new.visit_address=='200 Target St' and agent.lead.project_id==original_lead_project and agent.conversation.project_id==original_conv_project
    agent.turn('When is my visit?',understanding('When is my visit?','appointment').model_copy(update={'appointment_query':'active'}))
    assert 'Other Project' in latest(agent).content and '200 Target St' in latest(agent).content


@pytest.mark.parametrize('allowed,approved',[(True,False)])
def test_target_access_and_approval_required(agent,allowed,approved):
    _,_,old,_=book(agent);target_project(agent,enabled=allowed,approved=approved)
    text='Move my visit to Other Project';agent.turn(text,change(text,target_project='Other Project'))
    assert not latest(agent).metadata_json.get('reschedule_offer') and not agent.db.query(SalesRescheduleOperation).count()
    assert agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED and not agent.conversation.is_paused


def test_cross_company_project_name_cannot_be_used_as_a_target(agent):
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project
    _,_,old,_=book(agent)
    other=Company(name='Other Company');agent.db.add(other);agent.db.flush()
    foreign=Project(company_id=other.id,name='Private Target',address='SECRET ADDRESS');agent.db.add(foreign);agent.db.commit()
    text='Move my visit to Private Target';agent.turn(text,change(text,target_project='Private Target'))
    assert 'SECRET ADDRESS' not in agent.reply() and not agent.db.query(SalesRescheduleOperation).count()
    assert old.status==MeetingStatus.CONFIRMED


def test_target_company_project_policy_holds_cannot_be_waived(agent):
    from test_sales_ai_group_b import review
    _,_,old,_=book(agent);target,_,_=target_project(agent)
    original=agent.project;agent.project=target
    review(agent,project=True,rules=[{'id':'target-appointments','topics':['appointment'],'effect':'deny','reason':'Needs Sales review'}])
    agent.project=original
    text='Move my visit to Other Project';agent.turn(text,change(text,target_project='Other Project'))
    assert not latest(agent).metadata_json.get('reschedule_offer') and old.status==MeetingStatus.CONFIRMED


def test_multiple_current_visits_require_current_selection(agent):
    _,_,old,_=book(agent)
    another=meeting(agent,starts=datetime.utcnow()+timedelta(days=4))
    text='Change my visit';agent.turn(text,change(text))
    assert latest(agent).metadata_json.get('reschedule_meeting_offer')
    agent.turn('1',understanding('1','other'))
    offer=latest(agent).metadata_json.get('reschedule_offer')
    assert offer and offer['original']['id']==old.id
    assert agent.db.get(Meeting,another.id).status==MeetingStatus.CONFIRMED


def setup_old_calendar(agent):
    _,_,old,_=book(agent)
    connection=CalendarConnection(user_id=old.assigned_sales_user_id,provider='google',status='connected',calendar_id='old-calendar')
    agent.db.add(connection);old.gcal_event_id='old-owned-event';old.calendar_sync_status='synced'
    agent.db.query(SalesBookingOperation).filter_by(meeting_id=old.id).one().calendar_status='synced';agent.db.commit()
    return old,connection


def test_new_calendar_precedes_old_delete_and_retries_never_book_again(agent):
    old,connection=setup_old_calendar(agent);calls=[]
    def create(*a,**kw):calls.append('create');return {'id':kw['event_id']}
    def delete(*a,**kw):calls.append('delete')
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=create),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=delete):
        request_and_choose(agent)
        agent.turn('Yes',understanding('Yes','other'))
        op=agent.db.query(SalesRescheduleOperation).one()
        assert calls==['create','delete'] and op.calendar_status=='completed'
        from app.modules.sales_agent.reschedule_service import retry_effects
        retry_effects(agent.db)
        assert calls==['create','delete'] and agent.db.query(Meeting).count()==2


def test_new_calendar_failure_retains_old_event_until_new_event_exists(agent):
    old,connection=setup_old_calendar(agent)
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=RuntimeError('offline')),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        request_and_choose(agent);agent.turn('Yes',understanding('Yes','other'))
        delete.assert_not_called()
    op=agent.db.query(SalesRescheduleOperation).one();new_op=agent.db.get(SalesBookingOperation,op.replacement_booking_operation_id)
    assert new_op.calendar_status=='retry' and op.calendar_status=='waiting_new_calendar' and agent.db.query(Meeting).count()==2
    op.next_attempt_at=new_op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.reschedule_service import retry_effects
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'new-event'}) as create,\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        retry_effects(agent.db);retry_effects(agent.db)
        assert create.call_count==delete.call_count==1 and delete.call_args.args[-1]=='old-owned-event'
    assert agent.db.query(Meeting).count()==2


def test_delete_failure_retries_exact_old_event_without_creating_another_booking(agent):
    old,_=setup_old_calendar(agent)
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'new-event'}),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):
        request_and_choose(agent);agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();assert op.calendar_status=='retry' and op.attempts==1
    op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.reschedule_service import retry_effects
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection') as create,patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        retry_effects(agent.db);retry_effects(agent.db);create.assert_not_called();assert delete.call_count==1
    assert agent.db.query(Meeting).count()==2


def test_explicit_specialist_available_later_is_not_lost_to_earlier_other_slots(agent):
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    from app.modules.users.models import User,UserRole
    _,_,old,_=book(agent)
    user=User(company_id=agent.company.id,email='requested@example.invalid',first_name='Requested',last_name='Specialist',role=UserRole.SALES,is_active=True,hashed_password='OFFLINE')
    agent.db.add(user);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=agent.project.id,user_id=user.id,responsibility='sales',sales_enabled=True,is_active=True,accepts_appointments=True))
    when=old.meeting_time+timedelta(days=2)
    agent.db.add(SalesAvailabilityBlock(user_id=user.id,starts_at=when,ends_at=when+timedelta(hours=2),timezone='UTC'));agent.db.commit()
    text='Reschedule with Requested Specialist'
    request_and_choose(agent,text,target_specialist='Requested Specialist')
    assert load(agent.db,agent.scope)[1].reschedule_proposal['option']['sales_user_id']==user.id
    agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();assert agent.db.get(Meeting,op.replacement_meeting_id).assigned_sales_user_id==user.id
    process_notification_outbox(agent.db)
    assert agent.db.query(Notification).filter_by(recipient_user_id=old.assigned_sales_user_id,notification_type='appointment_rescheduled').count()==1
    assert agent.db.query(Notification).filter_by(recipient_user_id=user.id,notification_type='appointment_rescheduled').count()==1


def test_mixed_material_confirmation_preserves_replacement_truth(agent):
    from test_sales_turn_1720 import approved_asset
    old=prepare(agent)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    text='Yes, and send photos'
    u=Understanding.model_validate({**understanding(text,'appointment','materials',subjects={1:'photos'}).model_dump(),
        'reschedule':{'action':'confirm','evidence':'Yes'}})
    agent.turn(text,u)
    assert agent.db.query(SalesRescheduleOperation).count()==1 and 'Your visit has been rescheduled' in latest(agent).content
    assert latest(agent).content.count('?')==1 and latest(agent).metadata_json.get('material_offer')


def test_original_and_replacement_history_distinguish_reschedule_from_cancellation(agent):
    old=prepare(agent);agent.turn('Yes',understanding('Yes','other'))
    text='Show my appointment history'
    agent.turn(text,understanding(text,'appointment').model_copy(update={'appointment_query':'all'}))
    assert 'rescheduled (replaced)' in latest(agent).content and 'confirmed' in latest(agent).content
    assert agent.db.query(SalesRescheduleOperation).count()==1


def test_other_topic_does_not_authorize_a_pending_change(agent):
    from test_sales_turn_1720 import approved_asset
    old=prepare(agent)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan'])
    agent.turn('Send floor plans',understanding('Send floor plans','materials',subjects={0:'floor_plan'}))
    agent.turn('Yes',understanding('Yes','appointment'))
    assert not agent.db.query(SalesRescheduleOperation).count() and old.status==MeetingStatus.CONFIRMED


def test_injected_failure_after_new_meeting_flush_rolls_back_the_whole_replacement(agent):
    old=prepare(agent)
    from app.modules.sales_crm import scheduling
    original=scheduling.create_agent_appointment
    def fail(*a,**kw):original(*a,**kw);raise RuntimeError('fail after flushed replacement')
    with patch.object(scheduling,'create_agent_appointment',side_effect=fail):agent.turn('Yes',understanding('Yes','other'))
    agent.db.expire_all()
    assert agent.db.query(Meeting).count()==1 and agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED
    assert not agent.db.query(SalesRescheduleOperation).count()


def test_post_composition_target_approval_failure_restores_original(agent):
    old=prepare(agent)
    from app.modules.sales_agent import commercial_composer,reschedule_service
    compose=commercial_composer.compose;authorize=reschedule_service.authorize_target;after={'value':False}
    async def completed(*a,**kw):
        result=await compose(*a,**kw);after['value']=True;return result
    def guarded(*a,**kw):
        if after['value']:raise PermissionError('Approval revoked during composition')
        return authorize(*a,**kw)
    with patch.object(commercial_composer,'compose',side_effect=completed),patch.object(reschedule_service,'authorize_target',side_effect=guarded):
        agent.turn('Yes',understanding('Yes','other'))
    agent.db.expire_all()
    assert agent.db.query(Meeting).count()==1 and agent.db.get(Meeting,old.id).status==MeetingStatus.CONFIRMED
    assert not agent.db.query(SalesRescheduleOperation).count()


def test_no_replacement_available_never_releases_old_slot(agent):
    _,_,old,_=book(agent)
    text='Move my visit to 2099-01-01'
    agent.turn(text,change(text,timing={'date_from_evidence':'2099-01-01'}))
    assert old.status==MeetingStatus.CONFIRMED and agent.db.query(Meeting).count()==1
    assert not latest(agent).metadata_json.get('reschedule_offer') and not agent.conversation.is_paused


def test_duplicate_reschedule_with_same_original_cannot_replace_twice(agent):
    old=prepare(agent);proposal=load(agent.db,agent.scope)[1].reschedule_proposal
    agent.turn('Yes',understanding('Yes','other'))
    revision,state=load(agent.db,agent.scope);state.reschedule_proposal=proposal
    save(agent.db,agent.scope,event_key='stale-proposal',expected_revision=revision,state=state);agent.db.commit()
    outbound(agent.db,agent.conversation,'Confirm the old comparison?',{'reschedule_confirmation':{'id':proposal['id']}})
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(SalesRescheduleOperation).count()==1 and agent.db.query(Meeting).count()==2


def test_two_successive_changes_retire_oldest_event_after_latest_calendar_is_ready(agent):
    from app.modules.sales_agent.reschedule_service import advance_effect
    old,connection=setup_old_calendar(agent)
    def create(*a,**kw):return {'id':kw['event_id']}
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=create),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):
        request_and_choose(agent);agent.turn('Yes',understanding('Yes','other'))
    first=agent.db.query(SalesRescheduleOperation).one()
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',side_effect=create),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        request_and_choose(agent);agent.turn('Yes',understanding('Yes','other'))
        first.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit();advance_effect(agent.db,first.id)
        assert any(c.args[-1]=='old-owned-event' for c in delete.call_args_list)
    assert agent.db.query(Meeting).filter_by(status=MeetingStatus.CONFIRMED).count()==1
    assert agent.db.query(Meeting).count()==3 and first.calendar_status=='completed'


@pytest.mark.parametrize('variant',['overlap','all_day','pagination','malformed','overflow','empty'])
def test_calendar_excludes_only_exact_owned_event_and_fails_closed(variant):
    from types import SimpleNamespace
    from app.integrations.gcalendar_client import calendar_busy_ranges_excluding_event
    start=datetime(2030,1,1,10);end=start+timedelta(hours=1)
    owned={'id':'owned','start':{'dateTime':'2030-01-01T10:00:00Z'},'end':{'dateTime':'2030-01-01T11:00:00Z'}}
    other={**owned,'id':'other'}
    pages=[{'items':[owned,other]}]
    if variant=='all_day':pages=[{'timeZone':'America/Lima','items':[owned,{'id':'all','start':{'date':'2030-01-01'},'end':{'date':'2030-01-02'}}]}]
    if variant=='pagination':pages=[{'items':[owned],'nextPageToken':'next'},{'items':[other]}]
    if variant=='malformed':pages=[{}]
    if variant=='overflow':pages=[{'items':[owned],'nextPageToken':'more'}]*5
    if variant=='empty':pages=[{'kind':'calendar#events'}]
    responses=[Mock(json=Mock(return_value=p)) for p in pages]
    connection=SimpleNamespace(calendar_id='primary',last_error=None);db=Mock()
    with patch('app.integrations.gcalendar_client._access_token',return_value='offline'),patch('app.integrations.gcalendar_client.httpx.get',side_effect=responses) as get:
        result=calendar_busy_ranges_excluding_event(db,connection,starts_at=start,ends_at=end,event_id='owned')
    if variant=='all_day':assert result==[(datetime(2030,1,1,5),datetime(2030,1,2,5))]
    elif variant=='empty':assert result==[]
    else:assert result==[(start,end)]
    assert bool(connection.last_error)==(variant in {'malformed','overflow'})
    if variant=='pagination':assert get.call_count==2


def test_reschedule_migration_roundtrip_preserves_history():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_reschedule_operations.py'
    spec=importlib.util.spec_from_file_location('reschedule_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        for table in ['companies','projects','sales_conversations','leads','sales_booking_operations']:conn.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, visit_address TEXT)'))
        conn.execute(text("INSERT INTO meetings VALUES ('old', 'Original address')"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade();assert 'sales_reschedule_operations' in inspect(conn).get_table_names()
            module.downgrade();assert 'sales_reschedule_operations' not in inspect(conn).get_table_names()
            assert conn.execute(text('SELECT visit_address FROM meetings')).scalar()=='Original address'
    engine.dispose()


def test_reschedule_migration_postgres_ddl():
    import importlib.util,io
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_reschedule_operations.py'
    spec=importlib.util.spec_from_file_location('reschedule_sql',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})):module.upgrade()
    sql=output.getvalue()
    for column in ['proposal_id','original_meeting_id','replacement_meeting_id']:assert f'UNIQUE ({column})' in sql
    assert 'UPDATE meetings' not in sql and 'DELETE' not in sql.replace('ON DELETE CASCADE','')


def test_replacement_waits_for_new_calendar_even_without_old_external_event(agent):
    old=prepare(agent);agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();receipt=agent.db.get(SalesBookingOperation,op.replacement_booking_operation_id)
    assert not old.gcal_event_id and receipt.calendar_status=='waiting_connection'
    assert op.calendar_status=='waiting_new_calendar'
    new=agent.db.get(Meeting,op.replacement_meeting_id)
    agent.db.add(CalendarConnection(user_id=new.assigned_sales_user_id,provider='google',status='connected',calendar_id='new-calendar'))
    receipt.next_attempt_at=op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.reschedule_service import retry_effects
    with patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'new-event'}) as create,patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        retry_effects(agent.db);retry_effects(agent.db)
        assert create.call_count==1;delete.assert_not_called()
    assert receipt.calendar_status=='synced' and op.calendar_status=='completed' and agent.db.query(Meeting).count()==2


def test_first_booking_worker_does_not_bypass_reschedule_activation_checks(agent):
    prepare(agent);agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesRescheduleOperation).one();receipt=agent.db.get(SalesBookingOperation,op.replacement_booking_operation_id)
    receipt.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.first_booking import retry_calendars
    with patch('app.modules.sales_agent.first_booking.sync_calendar') as sync:
        retry_calendars(agent.db);sync.assert_not_called()
    assert receipt.calendar_status=='waiting_connection'
