"""Confirmed cancellation through real coordinator/state/dispatcher; providers are simulated."""
from datetime import datetime,timedelta
from unittest.mock import patch,Mock
import uuid
import pytest
from test_sales_ai_group_b import agent
from test_sales_ai_group_f import book,latest,visit,courtesy
from test_sales_ai_group_g import setup_old_calendar,request_and_choose
from test_sales_ai_group_c import product,meeting
from test_sales_ai_group_d import typed,req,ref
from test_sales_active_integration import understanding
from test_sales_turn_1720 import case,outbound,approved_asset
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.dialogue_store import load,save
from app.modules.sales_agent.models import SalesMessage,AgentRun
from app.modules.sales_agent.cancellation_models import SalesCancellationOperation
from app.modules.sales_agent.booking_models import SalesBookingOperation
from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
from app.modules.sales_crm.models import Meeting,MeetingStatus,CalendarConnection
from app.modules.governance.models import NotificationOutbox,Notification
from app.modules.governance.services import process_notification_outbox


def cancellation(text,action='request',**values):
    return Understanding.model_validate({**understanding(text,'appointment' if action!='reason' else 'other').model_dump(),
        'cancellation':{'action':action,'evidence':text,**values}})


def prepare(agent):
    _,_,row,_=book(agent)
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    assert latest(agent).metadata_json.get('cancellation_confirmation'),agent.db.query(AgentRun).all()[-1].output_snapshot
    return row


def cancelled(agent):
    row=prepare(agent);agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(SalesCancellationOperation).count()==1,agent.db.query(AgentRun).all()[-1].output_snapshot
    return row,agent.db.query(SalesCancellationOperation).one()


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_request_then_exact_confirmation_cancels_once_and_keeps_chat_open(agent,channel):
    agent.conversation.channel=channel;row=prepare(agent);snapshot=latest(agent).content
    assert row.status==MeetingStatus.CONFIRMED and agent.db.query(Meeting).count()==1
    for value in ['Generic development','Studio','100 Main St','UTC','45 minutes']:assert value in snapshot
    assert snapshot.count('?')==1
    agent.turn('Yes',understanding('Yes','other'));op=agent.db.query(SalesCancellationOperation).one();agent.db.refresh(row)
    assert row.status==MeetingStatus.CANCELLED and row.confirmation_status=='cancelled_by_lead'
    assert latest(agent).content.startswith('Your visit has been cancelled:') and latest(agent).content.count('?')==1
    assert 'reason' in latest(agent).content and 'notified' not in latest(agent).content
    assert op.calendar_status=='completed' and not agent.conversation.is_paused and not agent.lead.is_opt_out
    assert agent.db.query(SalesBookingOperation).one().calendar_status=='cancelled'
    state=load(agent.db,agent.scope)[1]
    assert state.cadence_status=='stopped' and state.cadence_stop_reason=='cancelled'
    agent.turn('Yes',understanding('Yes','appointment'))
    assert agent.db.query(Meeting).count()==agent.db.query(SalesCancellationOperation).count()==1


@pytest.mark.parametrize('text',['No','No thanks','No more questions'])
def test_no_declines_only_cancellation_proposal(agent,text):
    row=prepare(agent);agent.turn(text,understanding(text,'opt_out'))
    assert row.status==MeetingStatus.CONFIRMED and not agent.lead.is_opt_out
    assert not agent.db.query(SalesCancellationOperation).count() and 'kept your original reservation' in latest(agent).content


@pytest.mark.parametrize('kind,text',[('farewell','Goodbye'),('acknowledgement','Thank you'),('farewell','I have no more questions')])
def test_farewell_and_acknowledgement_never_cancel(agent,kind,text):
    _,_,row,_=book(agent);agent.turn(text,courtesy(text,kind))
    assert row.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_expired_proposal_keeps_reservation(agent):
    row=prepare(agent);rev,state=load(agent.db,agent.scope)
    from app.modules.sales_agent.turn_configuration import digest
    proposal=state.cancellation_proposal;proposal['expires_at']=(datetime.now().astimezone()-timedelta(minutes=1)).isoformat();proposal['id']=digest({k:v for k,v in proposal.items() if k!='id'})
    save(agent.db,agent.scope,event_key='expire',expected_revision=rev,state=state);agent.db.commit()
    msg=latest(agent);msg.metadata_json={**msg.metadata_json,'cancellation_confirmation':{'id':proposal['id']}};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert row.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count() and 'expired' in latest(agent).content


@pytest.mark.parametrize('change',['time','specialist','status'])
def test_changed_reservation_is_not_cancelled_from_old_summary(agent,change):
    row=prepare(agent)
    if change=='time':row.meeting_time+=timedelta(hours=1)
    if change=='specialist':row.assigned_sales_user_id=None
    if change=='status':row.status=MeetingStatus.IN_PROGRESS
    agent.db.commit();agent.turn('Yes',understanding('Yes','other'))
    assert row.status!=MeetingStatus.CANCELLED and not agent.db.query(SalesCancellationOperation).count()


@pytest.mark.parametrize('interruption',['human','incomplete','other'])
def test_only_immediate_complete_backend_summary_can_be_accepted(agent,interruption):
    row=prepare(agent)
    if interruption=='human':
        msg=outbound(agent.db,agent.conversation,'Can I help with something else?',{});msg.role='human';agent.db.commit()
    elif interruption=='incomplete':
        msg=latest(agent);msg.metadata_json={**msg.metadata_json,'delivery_group':{'key':'missing-parts','total':2,'part':1}};agent.db.commit()
    else:
        approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan'])
        agent.turn('Send floor plans',understanding('Send floor plans','materials',subjects={0:'floor_plan'}))
    agent.turn('Yes',understanding('Yes','appointment'))
    assert row.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_multiple_current_visits_require_choice_before_summary(agent):
    _,_,row,_=book(agent)
    other=meeting(agent,product_id=product(agent,'Loft').id,starts=row.meeting_time+timedelta(days=2));agent.db.commit()
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    assert latest(agent).metadata_json.get('cancellation_meeting_offer')
    agent.turn('2',understanding('2','other'))
    assert latest(agent).metadata_json.get('cancellation_confirmation') and 'Loft' in latest(agent).content
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.get(Meeting,other.id).status==MeetingStatus.CANCELLED and row.status==MeetingStatus.CONFIRMED


def test_optional_reason_is_recorded_after_cancellation_and_never_required(agent):
    row,op=cancelled(agent);text='My travel plans changed'
    agent.turn(text,cancellation(text,'reason',reason=text))
    agent.db.refresh(op)
    assert op.reason==text and op.reason_message_id and row.status==MeetingStatus.CANCELLED
    assert 'reason has been recorded' in latest(agent).content and latest(agent).content.count('?')==0


def test_no_to_optional_reason_does_not_opt_out_or_request_another_visit(agent):
    row,op=cancelled(agent);agent.turn('No',understanding('No','opt_out'))
    assert not agent.lead.is_opt_out and not agent.conversation.is_paused and agent.db.query(Meeting).count()==1
    assert 'No reason is required' in latest(agent).content and latest(agent).content.count('?')==0
    assert load(agent.db,agent.scope)[1].cadence_stop_reason=='cancelled'
    agent.turn('Tell me about the property',understanding('Tell me about the property','property_details'))
    assert not latest(agent).metadata_json.get('visit_invitation') and not latest(agent).metadata_json.get('appointment_offer')
    assert agent.db.query(Meeting).count()==1


def test_failure_after_cancel_flush_rolls_back_all_reservation_changes(agent):
    row=prepare(agent)
    with patch('app.modules.governance.services.enqueue_notification',side_effect=RuntimeError('outbox insert failed')):agent.turn('Yes',understanding('Yes','other'))
    agent.db.expire_all()
    assert agent.db.get(Meeting,row.id).status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()
    assert agent.db.query(SalesBookingOperation).one().calendar_status!='cancelled'


def test_calendar_delete_failure_keeps_cancellation_and_retries_exact_event(agent):
    row,connection=setup_old_calendar(agent)
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesCancellationOperation).one()
    assert row.status==MeetingStatus.CANCELLED and op.calendar_status=='retry' and op.attempts==1 and op.last_error=='RuntimeError'
    from app.modules.sales_agent.cancellation_service import retry_effects
    op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        retry_effects(agent.db);retry_effects(agent.db)
        assert delete.call_count==1 and delete.call_args.args[-1]=='old-owned-event'
    assert op.calendar_status=='completed' and agent.db.query(Meeting).count()==1


def test_notification_failure_visible_retryable_and_recipient_bound_to_cancelled_visit(agent):
    row,op=cancelled(agent);sales_id=row.assigned_sales_user_id;agent.lead.assigned_sales_user_id=None;agent.db.commit()
    from app.modules.governance import services
    original=services._process_notification_event
    def fail_cancel(db,event):
        if event.id==op.notification_outbox_id:raise RuntimeError('notice failure')
        return original(db,event)
    with patch.object(services,'_process_notification_event',side_effect=fail_cancel):process_notification_outbox(agent.db)
    assert op.notification_status=='retry' and op.notification_last_error=='RuntimeError' and row.status==MeetingStatus.CANCELLED
    event=agent.db.get(NotificationOutbox,op.notification_outbox_id);assert event.status=='pending'
    op.notification_next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    process_notification_outbox(agent.db);process_notification_outbox(agent.db)
    notices=agent.db.query(Notification).filter_by(notification_type='appointment_cancelled').all()
    assert len(notices)==1 and notices[0].recipient_user_id==sales_id and op.notification_status=='processed'


def test_legacy_cancel_directive_uses_exact_confirmation_not_first_booking(agent):
    _,_,row,_=book(agent);agent.turn('Cancel my visit',visit('Cancel my visit',action='cancel'))
    assert latest(agent).metadata_json.get('cancellation_confirmation') and row.status==MeetingStatus.CONFIRMED
    agent.turn('Yes',understanding('Yes','other'));assert row.status==MeetingStatus.CANCELLED


def test_no_future_or_in_progress_booking_is_never_invented_or_cancelled(agent):
    _,_,row,_=book(agent);row.status=MeetingStatus.IN_PROGRESS;agent.db.commit()
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    assert not latest(agent).metadata_json.get('cancellation_confirmation') and row.status==MeetingStatus.IN_PROGRESS
    assert not agent.db.query(SalesCancellationOperation).count()


def test_cross_scope_forged_proposal_never_cancels_other_lead(agent):
    row=prepare(agent)
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.turn_configuration import digest
    lead=Lead(company_id=agent.company.id,project_id=agent.project.id,full_name='Other lead',phone='+15550109999',source='manual',consent_status='granted')
    agent.db.add(lead);agent.db.flush();other=meeting(agent,lead=lead);agent.db.commit()
    rev,state=load(agent.db,agent.scope);p=state.cancellation_proposal;p['appointment']['id']=other.id;p['id']=digest({k:v for k,v in p.items() if k!='id'})
    save(agent.db,agent.scope,event_key='forged',expected_revision=rev,state=state);agent.db.commit()
    msg=latest(agent);msg.metadata_json={**msg.metadata_json,'cancellation_confirmation':{'id':p['id']}};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert row.status==other.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_reason_is_not_a_new_booking_and_needs_current_reason_question(agent):
    row,op=cancelled(agent)
    agent.turn('Tell me about the property',understanding('Tell me about the property','property_details'))
    text='Travel plans changed';agent.turn(text,cancellation(text,'reason',reason=text))
    assert op.reason is None and row.status==MeetingStatus.CANCELLED and agent.db.query(Meeting).count()==1


def test_cancel_after_reschedule_owns_pending_ancestor_calendar_cleanup(agent):
    row,connection=setup_old_calendar(agent)
    with patch('app.integrations.gcalendar_client.calendar_busy_ranges_excluding_event',return_value=[]),\
         patch('app.integrations.gcalendar_client.create_calendar_event_for_connection',return_value={'id':'new-owned-event'}),\
         patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):
        request_and_choose(agent);agent.turn('Yes',understanding('Yes','other'))
    previous=agent.db.query(SalesRescheduleOperation).one();assert previous.calendar_status=='retry'
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:
        agent.turn('Yes',understanding('Yes','other'))
        assert {c.args[-1] for c in delete.call_args_list}=={'old-owned-event','new-owned-event'}
        from app.modules.sales_agent.reschedule_service import advance_effect
        advance_effect(agent.db,previous.id)
        assert delete.call_count==2
    op=agent.db.query(SalesCancellationOperation).one()
    assert op.calendar_status=='completed' and previous.calendar_status=='cancelled'
    assert not agent.db.query(Meeting).filter_by(status=MeetingStatus.CONFIRMED).count()


def test_cancel_recovers_deterministic_event_after_creation_timeout(agent):
    row,connection=setup_old_calendar(agent);row.gcal_event_id=None
    receipt=agent.db.query(SalesBookingOperation).one();receipt.calendar_attempts=1;receipt.calendar_status='retry';agent.db.commit()
    agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete,patch('app.integrations.gcalendar_client.create_calendar_event_for_connection') as create:
        agent.turn('Yes',understanding('Yes','other'))
        from app.modules.sales_agent.first_booking import retry_calendars
        retry_calendars(agent.db);create.assert_not_called()
        assert delete.call_count==1 and delete.call_args.args[-1]=='bp'+row.id.replace('-','')


def test_mixed_material_confirmation_has_true_cancellation_and_only_one_question(agent):
    row=prepare(agent);approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    text='Yes, and send photos'
    u=Understanding.model_validate({**understanding(text,'appointment','materials',subjects={1:'photos'}).model_dump(),
        'cancellation':{'action':'confirm','evidence':'Yes'}})
    agent.turn(text,u)
    assert row.status==MeetingStatus.CANCELLED and 'Your visit has been cancelled:' in latest(agent).content
    assert latest(agent).content.count('?')==1 and latest(agent).metadata_json.get('material_offer')
    assert 'reason for cancelling' not in latest(agent).content


def test_cancel_summary_hidden_by_material_offer_cannot_be_confirmed(agent):
    _,_,row,_=book(agent);approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    text='Cancel my visit and send photos'
    u=Understanding.model_validate({**understanding(text,'appointment','materials',subjects={1:'photos'}).model_dump(),
        'cancellation':{'action':'request','evidence':'Cancel my visit'}})
    agent.turn(text,u);assert latest(agent).metadata_json.get('material_offer') and not latest(agent).metadata_json.get('cancellation_confirmation')
    agent.turn('Yes',understanding('Yes','other'))
    assert row.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_cancellation_frees_local_slot_without_changing_specialist_routing(agent):
    row=prepare(agent);user=row.assigned_sales_user_id;cursor=agent.project.next_sales_user_id if hasattr(agent.project,'next_sales_user_id') else None
    from app.modules.sales_crm.scheduling import _is_free
    args=dict(user_id=user,starts_at=row.meeting_time,ends_at=row.meeting_time+timedelta(minutes=45),external_busy=[])
    assert not _is_free(agent.db,**args)
    agent.turn('Yes',understanding('Yes','other'))
    assert _is_free(agent.db,**args) and agent.lead.assigned_sales_user_id==user
    if hasattr(agent.project,'next_sales_user_id'):assert agent.project.next_sales_user_id==cursor


def test_post_composition_permission_change_rolls_back_cancellation(agent):
    row=prepare(agent)
    from app.modules.sales_agent import commercial_composer,cancellation_service
    compose=commercial_composer.compose;authorize=cancellation_service.authorize;after={'value':False}
    async def composed(*a,**kw):
        result=await compose(*a,**kw);after['value']=True;return result
    def guarded(*a,**kw):
        if after['value']:raise PermissionError('Permission changed during composition')
        return authorize(*a,**kw)
    with patch.object(commercial_composer,'compose',side_effect=composed),patch.object(cancellation_service,'authorize',side_effect=guarded):agent.turn('Yes',understanding('Yes','other'))
    agent.db.expire_all()
    assert agent.db.get(Meeting,row.id).status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_notification_budget_and_manager_retry_are_visible_and_idempotent(agent):
    row,op=cancelled(agent)
    from app.modules.sales_agent.cancellation_service import reset_effects
    from app.modules.governance import services,router
    original=services._process_notification_event
    def fail(db,event):
        if event.id==op.notification_outbox_id:raise RuntimeError('offline')
        return original(db,event)
    for _ in range(5):
        op.notification_next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
        with patch.object(services,'_process_notification_event',side_effect=fail):process_notification_outbox(agent.db)
    assert op.notification_status=='review' and op.notification_attempts==5
    assert router.cancellation_effects(op.id,db=agent.db,current_user=manager(agent))['notification']['last_error']=='RuntimeError'
    reset_effects(agent.db,op);process_notification_outbox(agent.db);process_notification_outbox(agent.db)
    assert op.notification_status=='processed' and agent.db.query(Notification).filter_by(notification_type='appointment_cancelled').count()==1
    assert agent.db.query(Meeting).count()==1 and row.status==MeetingStatus.CANCELLED


def manager(agent):
    from app.modules.users.models import User,UserRole
    user=User(company_id=agent.company.id,email='manager-'+uuid.uuid4().hex+'@example.invalid',role=UserRole.ADMIN,first_name='Manager',hashed_password='OFFLINE',is_active=True)
    agent.db.add(user);agent.db.commit();return user


def test_effect_endpoints_check_role_company_and_project_access(agent):
    from app.modules.governance import router
    from app.modules.users.models import UserRole
    from app.modules.auth.deps import RoleChecker
    from fastapi import HTTPException
    row,op=cancelled(agent);user=manager(agent)
    assert router.cancellation_effects(op.id,db=agent.db,current_user=user)['cancelled']
    user.role=UserRole.SALES
    with pytest.raises(HTTPException) as caught:RoleChecker([UserRole.ADMIN,UserRole.ASSISTANT])(user)
    assert caught.value.status_code==403
    user.role=UserRole.ADMIN;user.company_id=str(uuid.uuid4())
    with pytest.raises(HTTPException) as caught:router.cancellation_effects(op.id,db=agent.db,current_user=user)
    assert caught.value.status_code==404
    agent.db.rollback()


def test_legacy_cancelled_notice_without_h_receipt_still_processes(agent):
    _,_,row,_=book(agent)
    from app.modules.governance.services import enqueue_notification
    enqueue_notification(agent.db,company_id=agent.company.id,project_id=agent.project.id,event_type='appointment_cancelled',entity_type='lead',entity_id=agent.lead.id,payload={},dedupe_key='legacy-cancel');agent.db.commit()
    process_notification_outbox(agent.db)
    assert agent.db.query(NotificationOutbox).filter_by(dedupe_key='legacy-cancel').one().status=='processed'


def test_explicit_new_visit_after_cancellation_still_needs_selection_and_confirmation(agent):
    old,op=cancelled(agent)
    agent.turn('I want to arrange a new visit',visit('I want to arrange a new visit'))
    assert latest(agent).metadata_json.get('appointment_offer') and agent.db.query(Meeting).count()==1
    agent.turn('1',typed('1',[req('time','appointment','1',ref='t')],[ref('t','appointment','1')]))
    assert latest(agent).metadata_json.get('booking_confirmation') and agent.db.query(Meeting).count()==1
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).count()==2 and old.status==MeetingStatus.CANCELLED
    assert agent.db.query(Meeting).filter_by(status=MeetingStatus.CONFIRMED).count()==1


def test_calendar_retry_budget_and_reset_do_not_repeat_cancellation(agent):
    row,connection=setup_old_calendar(agent);agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    from app.modules.sales_agent.cancellation_service import advance_effect,reset_effects
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')) as delete:
        agent.turn('Yes',understanding('Yes','other'));op=agent.db.query(SalesCancellationOperation).one()
        for _ in range(4):
            op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit();advance_effect(agent.db,op.id)
        advance_effect(agent.db,op.id)
        assert delete.call_count==5 and op.calendar_status=='review' and op.last_error=='RuntimeError'
    reset_effects(agent.db,op)
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:advance_effect(agent.db,op.id);advance_effect(agent.db,op.id);assert delete.call_count==1
    assert op.calendar_status=='completed' and agent.db.query(SalesCancellationOperation).count()==agent.db.query(Meeting).count()==1


@pytest.mark.parametrize('changed',['event','calendar','connection','meeting'])
def test_cleanup_never_deletes_a_changed_calendar_binding(agent,changed):
    row,connection=setup_old_calendar(agent);agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesCancellationOperation).one()
    if changed=='event':row.gcal_event_id='different-event'
    if changed=='calendar':connection.calendar_id='other-calendar'
    if changed=='connection':connection.provider='changed-provider'
    if changed=='meeting':row.status=MeetingStatus.CONFIRMED
    op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.cancellation_service import advance_effect
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:advance_effect(agent.db,op.id);delete.assert_not_called()
    assert op.calendar_status=='review' and op.last_error=='CalendarBindingChanged'


def test_disconnected_calendar_waits_for_same_connection_recovery(agent):
    row,connection=setup_old_calendar(agent);connection.status='disconnected';agent.db.commit()
    agent.turn('Cancel my visit',cancellation('Cancel my visit'));agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesCancellationOperation).one();assert op.calendar_status=='waiting_connection'
    connection.status='connected';op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    from app.modules.sales_agent.cancellation_service import advance_effect
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:advance_effect(agent.db,op.id);assert delete.call_count==1
    assert op.calendar_status=='completed'


def test_disabled_scope_does_not_run_calendar_cleanup(agent,monkeypatch):
    from app.core.config import settings
    row,connection=setup_old_calendar(agent);agent.turn('Cancel my visit',cancellation('Cancel my visit'))
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection',side_effect=RuntimeError('offline')):agent.turn('Yes',understanding('Yes','other'))
    op=agent.db.query(SalesCancellationOperation).one();op.next_attempt_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS','')
    from app.modules.sales_agent.cancellation_service import retry_effects,advance_effect
    with patch('app.integrations.gcalendar_client.delete_calendar_event_for_connection') as delete:retry_effects(agent.db);advance_effect(agent.db,op.id);delete.assert_not_called()
    assert op.calendar_status=='retry' and row.status==MeetingStatus.CANCELLED


def test_cancellation_does_not_require_property_to_still_be_sellable(agent):
    row=prepare(agent)
    from app.modules.projects.models import ProjectPropertyType
    agent.db.get(ProjectPropertyType,row.visit_property_type_id).review_status='draft';agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'))
    assert row.status==MeetingStatus.CANCELLED and agent.db.query(SalesCancellationOperation).count()==1


def test_late_target_policy_denial_keeps_reservation(agent):
    row=prepare(agent)
    with patch('app.modules.sales_agent.cancellation_service.authorize',side_effect=PermissionError('Access revoked')):agent.turn('Yes',understanding('Yes','other'))
    assert row.status==MeetingStatus.CONFIRMED and not agent.db.query(SalesCancellationOperation).count()


def test_delivery_failure_retry_reuses_one_cancellation_and_no_extra_effect(agent):
    row=prepare(agent);agent.send.side_effect=RuntimeError('SMS offline')
    with pytest.raises(RuntimeError):agent.turn('Yes',understanding('Yes','other'))
    inbound=agent.db.query(SalesMessage).filter_by(direction='inbound').order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    assert row.status==MeetingStatus.CANCELLED and agent.db.query(SalesCancellationOperation).count()==1
    agent.send.side_effect=lambda *a,**kw:{'sid':str(uuid.uuid4()),'status':'sent'}
    agent.retry(inbound)
    assert agent.db.query(SalesCancellationOperation).count()==agent.db.query(Meeting).count()==1
    assert agent.db.query(NotificationOutbox).filter_by(event_type='appointment_cancelled').count()==1


def test_cancellation_migration_roundtrip_preserves_meetings_and_existing_outbox():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_cancellation_operations.py'
    spec=importlib.util.spec_from_file_location('cancel_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        for table in ['companies','projects','sales_conversations','leads','sales_messages']:connection.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        for table in ['meetings','notification_outbox']:
            connection.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, value TEXT)'))
            connection.execute(text(f"INSERT INTO {table} VALUES ('old','unchanged')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade();assert 'sales_cancellation_operations' in inspect(connection).get_table_names()
            module.downgrade();assert 'sales_cancellation_operations' not in inspect(connection).get_table_names()
            for table in ['meetings','notification_outbox']:assert connection.execute(text(f'SELECT value FROM {table}')).scalar()=='unchanged'
    engine.dispose()


def test_cancellation_migration_postgres_ddl_is_additive():
    import importlib.util,io
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_cancellation_operations.py'
    spec=importlib.util.spec_from_file_location('cancel_sql',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})):module.upgrade()
    sql=output.getvalue();assert 'UNIQUE (proposal_id)' in sql and 'UNIQUE (meeting_id)' in sql
    assert 'UPDATE meetings' not in sql and 'DELETE' not in sql.replace('ON DELETE CASCADE','').replace('ON DELETE SET NULL','')


def test_voluntary_reason_in_request_is_saved_without_asking_again(agent):
    _,_,row,_=book(agent);text='Cancel my visit because my travel plans changed'
    request,_=agent.turn(text,cancellation(text,reason='my travel plans changed'))
    agent.turn('Yes',understanding('Yes','other'));op=agent.db.query(SalesCancellationOperation).one()
    assert op.reason=='my travel plans changed' and op.reason_message_id==request.id
    assert 'reason has been recorded' in latest(agent).content and 'reason for cancelling' not in latest(agent).content
    assert not latest(agent).metadata_json.get('cancellation_followup')


def test_decline_does_not_claim_an_already_cancelled_reservation_was_kept(agent):
    row=prepare(agent);row.status=MeetingStatus.CANCELLED;agent.db.commit()
    agent.turn('No',understanding('No','other'))
    assert 'kept your original reservation' not in latest(agent).content and not agent.db.query(SalesCancellationOperation).count()


@pytest.mark.parametrize('status',[204,404,410,403,500])
def test_calendar_delete_recognizes_already_deleted_event_but_not_permission_or_server_errors(status):
    import httpx
    from types import SimpleNamespace
    from app.integrations.gcalendar_client import delete_calendar_event_for_connection
    response=httpx.Response(status,request=httpx.Request('DELETE','https://calendar.example.invalid/event'))
    with patch('app.integrations.gcalendar_client._access_token',return_value='offline'),patch('app.integrations.gcalendar_client.httpx.delete',return_value=response) as delete:
        if status in {403,500}:
            with pytest.raises(httpx.HTTPStatusError):delete_calendar_event_for_connection(Mock(),SimpleNamespace(calendar_id='owned-calendar'),'owned-event')
        else:delete_calendar_event_for_connection(Mock(),SimpleNamespace(calendar_id='owned-calendar'),'owned-event')
        assert delete.call_args.args[0].endswith('/calendars/owned-calendar/events/owned-event')
