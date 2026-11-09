"""Availability alerts with real coordinator, persisted waits and dispatcher; no live sends."""
import asyncio,uuid
from datetime import datetime,timedelta
from unittest.mock import patch
import pytest
from test_sales_turn_1720 import case,outbound,approved_asset
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product
from test_sales_ai_group_d import availability,typed,req,ref
from test_sales_ai_group_f import visit,latest,book
from test_sales_ai_group_g import change
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.wait_models import SalesWaitRequest
from app.modules.sales_agent import wait_service
from app.modules.sales_agent.dialogue_store import load,save
from app.modules.sales_agent.models import SalesMessage,OutboundMessage,AgentRun
from app.modules.sales_crm.models import Meeting,MeetingStatus,SalesAvailabilityBlock
from app.core.config import settings


def wait(text,action='request',timing=None):
    return Understanding.model_validate({**understanding(text,'appointment').model_dump(),'wait':{'action':action,'evidence':text,'timing':timing}})


def offer(agent):
    start=availability(agent);product(agent,'Studio')
    blocks=agent.db.query(SalesAvailabilityBlock).all()
    for block in blocks:agent.db.delete(block)
    agent.db.commit();agent.turn('I want to arrange a visit',visit('I want to arrange a visit'))
    assert latest(agent).metadata_json.get('wait_offer'),agent.db.query(AgentRun).all()[-1].output_snapshot
    return start


def registered(agent):
    starts=offer(agent);message,run=agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(SalesWaitRequest).count()==1,run.output_snapshot
    return agent.db.query(SalesWaitRequest).one(),starts


def add_block(agent,starts):
    from app.modules.project_team.models import ProjectUserAssignment
    user=agent.db.query(ProjectUserAssignment).filter_by(project_id=agent.project.id).first().user_id
    agent.db.add(SalesAvailabilityBlock(user_id=user,starts_at=starts,ends_at=starts+timedelta(hours=2),timezone='UTC'));agent.db.commit()


def worker(agent):
    with agent.patched(),patch('app.db.postgres.SessionLocal',return_value=agent.db),patch.object(agent.db,'close'):
        asyncio.run(wait_service.process_due())


def due(agent,row):
    row.next_check_at=datetime.utcnow()-timedelta(seconds=1);row.lease_until=None;agent.db.commit()


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_no_promise_without_explicit_optin_and_persistent_scoped_preferences(agent,channel):
    agent.conversation.channel=channel;starts=offer(agent)
    assert not agent.db.query(SalesWaitRequest).count() and not agent.db.query(Meeting).count()
    assert latest(agent).content.count('?')==1 and 'Would you like me to save' in latest(agent).content
    agent.turn('Yes',understanding('Yes','other'));row=agent.db.query(SalesWaitRequest).one()
    assert row.status=='waiting' and row.channel==channel and row.requested_message_id
    assert row.snapshot_json['context']['property_type_name']=='Studio' and row.snapshot_json['preferences']['timezone']=='UTC'
    assert row.snapshot_json['preferences']['date_from'] and row.snapshot_json['preferences']['date_until'] and row.expires_at>datetime.utcnow()
    assert 'request is saved' in latest(agent).content and not agent.db.query(Meeting).count()
    worker(agent);assert row.status=='waiting' and row.notified_message_id is None


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_verified_alert_is_deduplicated_and_requires_normal_booking_confirmation(agent,channel):
    agent.conversation.channel=channel;row,starts=registered(agent);add_block(agent,starts);before=agent.send.await_count
    worker(agent)
    assert row.status=='notified',row.last_error
    assert agent.send.await_count>before and latest(agent).metadata_json.get('appointment_offer')
    assert 'Verified visit options' in latest(agent).content and not agent.db.query(Meeting).count()
    sent=agent.send.await_count;worker(agent);assert agent.send.await_count==sent
    agent.turn('1',typed('1',[req('t','appointment','1',ref='s')],[ref('s','appointment','1')]))
    assert latest(agent).metadata_json.get('booking_confirmation') and not agent.db.query(Meeting).count()
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).count()==1 and row.status=='notified'


def test_duplicate_explicit_request_reuses_one_active_record(agent):
    row,starts=registered(agent)
    agent.turn('Please notify me if a time becomes available',wait('Please notify me if a time becomes available'))
    assert agent.db.query(SalesWaitRequest).count()==1 and 'already saved' in latest(agent).content and row.active_key


def test_no_to_alert_question_is_not_channel_optout(agent):
    offer(agent);agent.turn('No',understanding('No','opt_out'))
    assert not agent.db.query(SalesWaitRequest).count() and not agent.lead.is_opt_out and not agent.conversation.is_paused


def test_alert_cancellation_does_not_cancel_an_appointment(agent):
    row,starts=registered(agent)
    _,run=agent.turn('Cancel my alert request',wait('Cancel my alert request','cancel'))
    assert row.status=='closed' and row.close_reason=='cancelled_by_lead' and not agent.db.query(Meeting).count(),run.output_snapshot
    assert 'existing reservation is unchanged' in latest(agent).content


def test_other_offer_yes_does_not_register_wait(agent):
    offer(agent);approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    agent.turn('Send photos',understanding('Send photos','materials',subjects={0:'photos'}))
    agent.turn('Yes',wait('Yes'))
    assert not agent.db.query(SalesWaitRequest).count()


def test_opt_out_closes_wait_and_worker_does_not_contact(agent):
    row,starts=registered(agent);agent.turn('STOP',understanding('STOP','other'))
    assert row.status=='closed' and row.close_reason=='consent_withdrawn'
    add_block(agent,starts);before=agent.send.await_count;worker(agent);assert agent.send.await_count==before


def test_interest_change_closes_wait_without_booking(agent):
    row,starts=registered(agent);product(agent,'Loft')
    text='Tell me about Loft';agent.turn(text,typed(text,[req('p','property_details',text,ref='p')],[ref('p','property','Loft')]))
    assert row.status=='closed' and row.close_reason=='interest_changed' and not agent.db.query(Meeting).count()


def test_expired_wait_cannot_send_even_when_availability_returns(agent):
    row,starts=registered(agent);row.expires_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit();add_block(agent,starts)
    before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and row.close_reason=='expired' and agent.send.await_count==before


def test_withdrawn_consent_from_another_entrypoint_blocks_contact(agent):
    row,starts=registered(agent);agent.lead.consent_status='revoked';agent.db.commit();add_block(agent,starts)
    before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and agent.send.await_count==before


def test_closed_whatsapp_window_defers_without_template_or_sms_fallback(agent):
    agent.conversation.channel='whatsapp';row,starts=registered(agent);add_block(agent,starts)
    for msg in agent.db.query(SalesMessage).filter_by(direction='inbound').all():msg.created_at=datetime.utcnow()-timedelta(days=2)
    agent.db.commit();before=agent.send.await_count;worker(agent)
    assert row.status=='blocked_channel' and row.last_error=='WhatsAppWindowClosed' and agent.send.await_count==before
    agent.turn('Thank you',understanding('Thank you','other'));due(agent,row);worker(agent)
    assert row.status=='notified',row.last_error


def test_ambiguous_provider_exception_is_visible_and_not_automatically_resent(agent):
    row,starts=registered(agent);add_block(agent,starts);agent.send.side_effect=RuntimeError('network timeout')
    worker(agent)
    assert row.status=='review' and row.last_error=='RuntimeError' and not agent.db.query(Meeting).count()
    count=agent.send.await_count;due(agent,row);worker(agent);assert agent.send.await_count==count


def test_manual_control_prevents_wait_contact(agent):
    row,starts=registered(agent);add_block(agent,starts);agent.conversation.is_paused=True;agent.conversation.pause_reason='Manual control active';agent.db.commit()
    before=agent.send.await_count;worker(agent)
    assert row.status=='blocked_channel' and row.last_error=='ManualControl' and agent.send.await_count==before


def test_restart_reloads_wait_and_checks_current_availability(agent):
    row,starts=registered(agent);identifier=row.id;agent.db.expunge(row);row=agent.db.get(SalesWaitRequest,identifier)
    add_block(agent,starts);worker(agent)
    assert row.status=='notified' and row.notified_message_id


def test_no_persistence_means_no_saved_alert_promise(agent):
    offer(agent)
    with patch('app.modules.sales_agent.wait_service.validate_saved',side_effect=ValueError('write failed')):agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesWaitRequest).count() and 'request is saved' not in latest(agent).content


def test_nearby_dates_are_explicit_keep_time_preferences_and_never_book(agent):
    starts=availability(agent);product(agent,'Studio')
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();day=starts.date().isoformat();text=f'I want a visit on {day} at 3 PM'
    agent.turn(text,visit(text,timing={'date_from_evidence':day,'time_from_evidence':'3 PM','time_relation':'exact'}))
    assert latest(agent).metadata_json.get('wait_offer')
    assert not agent.db.query(SalesWaitRequest).count()
    add_block(agent,starts+timedelta(days=1))
    agent.turn('Show nearby dates',wait('Show nearby dates','nearby'))
    result=latest(agent).metadata_json.get('appointment_offer');assert result,agent.db.query(AgentRun).all()[-1].output_snapshot
    assert result['preferences']['time_relation']=='exact' and result['preferences']['time_from']=='15:00'
    assert result['preferences']['timezone']=='UTC' and result['context']['property_type_name']=='Studio'
    assert all(datetime.fromisoformat(v['starts_at']).hour==15 for v in result['options'])
    assert all(datetime.fromisoformat(v['starts_at']).date()!=starts.date() for v in result['options'])
    assert not agent.db.query(Meeting).count() and not agent.db.query(SalesWaitRequest).count()


def test_reschedule_wait_keeps_original_then_requires_exact_replacement_confirmation(agent):
    _,_,old,starts=book(agent)
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();agent.turn('I want to reschedule my visit',change('I want to reschedule my visit'))
    assert latest(agent).metadata_json.get('wait_offer') and old.status==MeetingStatus.CONFIRMED
    agent.turn('Yes',understanding('Yes','other'));row=agent.db.query(SalesWaitRequest).one()
    assert row.snapshot_json['original']['id']==old.id and old.status==MeetingStatus.CONFIRMED
    add_block(agent,starts+timedelta(days=1));worker(agent)
    assert row.status=='notified',row.last_error
    assert latest(agent).metadata_json.get('reschedule_offer') and old.status==MeetingStatus.CONFIRMED
    agent.turn('1',typed('1',[req('t','appointment','1',ref='t')],[ref('t','appointment','1')]))
    assert latest(agent).metadata_json.get('reschedule_confirmation') and old.status==MeetingStatus.CONFIRMED
    agent.turn('Yes',understanding('Yes','other'))
    assert old.status==MeetingStatus.CANCELLED and agent.db.query(Meeting).filter_by(status=MeetingStatus.CONFIRMED).count()==1


def test_cancel_wait_during_rescheduling_keeps_old_reservation(agent):
    _,_,old,starts=book(agent)
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();agent.turn('Reschedule my visit',change('Reschedule my visit'));agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(SalesWaitRequest).one()
    agent.turn('Cancel my alert request',wait('Cancel my alert request','cancel'))
    assert row.status=='closed' and old.status==MeetingStatus.CONFIRMED and agent.db.query(Meeting).count()==1


def test_appointment_cancellation_closes_its_rescheduling_wait(agent):
    from test_sales_ai_group_h import cancellation
    _,_,old,starts=book(agent)
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();agent.turn('Reschedule my visit',change('Reschedule my visit'));agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(SalesWaitRequest).one()
    agent.turn('Cancel my visit',cancellation('Cancel my visit'));agent.turn('Yes',understanding('Yes','other'))
    assert old.status==MeetingStatus.CANCELLED and row.status=='closed' and row.close_reason=='appointment_cancelled'


def test_booking_elsewhere_closes_pending_wait(agent):
    row,starts=registered(agent);add_block(agent,starts)
    agent.turn('I want to arrange a visit',visit('I want to arrange a visit'))
    agent.turn('1',typed('1',[req('t','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).count()==1 and row.status=='closed' and row.close_reason=='booked'


@pytest.mark.parametrize('kind',['phone','provider','channel'])
def test_contact_changes_never_redirect_a_saved_alert(agent,kind):
    row,starts=registered(agent);add_block(agent,starts)
    if kind=='phone':agent.lead.phone='+15550109999'
    if kind=='provider':agent.conversation.provider='changed-provider'
    if kind=='channel':agent.conversation.channel='whatsapp'
    agent.db.commit();before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and row.close_reason=='contact_changed' and agent.send.await_count==before


def test_operating_window_defers_proactive_contact(agent):
    row,starts=registered(agent);add_block(agent,starts);future=datetime.utcnow()+timedelta(hours=2)
    before=agent.send.await_count
    with patch('app.modules.governance.services.next_allowed_proactive_time',return_value=future):worker(agent)
    assert row.status=='blocked_channel' and row.next_check_at>=future and row.last_error=='OperatingWindowClosed'
    assert agent.send.await_count==before


def test_disabled_cohort_never_claims_or_sends_wait(agent,monkeypatch):
    row,starts=registered(agent);add_block(agent,starts);before=agent.send.await_count
    monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS','');worker(agent)
    assert row.status=='waiting' and agent.send.await_count==before


def test_provider_known_rejection_retries_stable_parts_without_new_booking(agent):
    row,starts=registered(agent);add_block(agent,starts)
    agent.send.side_effect=lambda *a,**kw:{'sid':None,'status':'failed'}
    worker(agent)
    assert row.status=='retry' and row.last_error=='ProviderRejected',row.last_error
    prepared=row.notice_json
    due(agent,row);agent.send.side_effect=lambda *a,**kw:{'sid':str(uuid.uuid4()),'status':'sent'}
    worker(agent);assert row.status=='notified' and row.notice_json==prepared and row.attempts==2
    assert not agent.db.query(Meeting).count()
    count=agent.send.await_count;worker(agent);assert agent.send.await_count==count


def test_restart_after_provider_accepted_does_not_repeat_notice(agent):
    row,starts=registered(agent);add_block(agent,starts);worker(agent)
    assert row.status=='notified';count=agent.send.await_count
    row.status='processing';row.closed_at=None;row.lease_until=datetime.utcnow()-timedelta(seconds=1);row.next_check_at=datetime.utcnow()-timedelta(seconds=1);agent.db.commit()
    worker(agent)
    assert row.status=='notified' and agent.send.await_count==count


def test_unprocessed_new_inbound_defers_notice_before_interpretation(agent):
    row,starts=registered(agent);add_block(agent,starts)
    msg=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='Tell me about another property',status='received')
    agent.db.add(msg);agent.db.commit();before=agent.send.await_count;worker(agent)
    assert row.status=='blocked_channel' and row.last_error=='InboundTurnPending' and agent.send.await_count==before


def test_live_last_boundary_catches_consent_change_before_provider(agent):
    row,starts=registered(agent);add_block(agent,starts);original=wait_service.authorize_part;before=agent.send.await_count
    def change_before_send(db,conversation,lead,metadata,content,**kw):
        if kw.get('before_provider'):
            lead.is_opt_out=True;lead.consent_status='opted_out';db.commit()
        return original(db,conversation,lead,metadata,content,**kw)
    with patch.object(wait_service,'authorize_part',side_effect=change_before_send):worker(agent)
    assert row.status=='closed' and agent.send.await_count==before and not agent.db.query(Meeting).count()


def test_manual_offer_cannot_authorize_wait_from_bare_yes(agent):
    offer(agent);outbound(agent.db,agent.conversation,'Would you like an alert?',{})
    agent.turn('Yes',wait('Yes'))
    assert not agent.db.query(SalesWaitRequest).count()


def test_wait_registration_expired_offer_is_not_saved(agent):
    offer(agent);rev,state=load(agent.db,agent.scope)
    from app.modules.sales_agent.turn_configuration import digest
    value=state.wait_context;value['expires_at']=(datetime.now().astimezone()-timedelta(seconds=1)).isoformat();value['id']=digest({k:v for k,v in value.items() if k!='id'})
    save(agent.db,agent.scope,event_key='expire-wait-offer',expected_revision=rev,state=state);agent.db.commit()
    msg=latest(agent);msg.metadata_json={**msg.metadata_json,'wait_offer':value};agent.db.commit()
    agent.turn('Yes',understanding('Yes','other'));assert not agent.db.query(SalesWaitRequest).count()


def test_appointment_prohibition_is_not_implicitly_released_by_alert_request(agent):
    row,starts=registered(agent)
    text='I do not want any appointment alerts'
    agent.turn(text,Understanding.model_validate({**understanding(text,'other').model_dump(),
        'constraints':[{'topic':'appointment','subject':None,'evidence':text,'scope':'until_explicit_change'}]}))
    add_block(agent,starts);before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and agent.send.await_count==before


def test_superseded_worker_claim_cannot_send_after_lease_takeover(agent):
    row,starts=registered(agent);add_block(agent,starts);original=wait_service.authorize_part;before=agent.send.await_count
    def takeover(db,conversation,lead,metadata,content,**kw):
        if kw.get('before_provider'):
            row.claim_token='new-worker-claim';db.commit()
        return original(db,conversation,lead,metadata,content,**kw)
    with patch.object(wait_service,'authorize_part',side_effect=takeover):worker(agent)
    assert agent.send.await_count==before and row.claim_token=='new-worker-claim' and not agent.db.query(Meeting).count()


def test_offered_slot_disappearing_before_provider_never_produces_an_alert(agent):
    row,starts=registered(agent);add_block(agent,starts);original=wait_service.authorize_part;before=agent.send.await_count
    def unavailable(db,conversation,lead,metadata,content,**kw):
        if kw.get('before_provider'):
            for block in db.query(SalesAvailabilityBlock).all():db.delete(block)
            db.commit()
        return original(db,conversation,lead,metadata,content,**kw)
    with patch.object(wait_service,'authorize_part',side_effect=unavailable):worker(agent)
    assert row.status=='closed' and row.close_reason=='offered_time_changed' and agent.send.await_count==before


def test_saved_context_revocation_closes_wait_without_sending(agent):
    from app.modules.projects.models import ProjectPropertyType
    row,starts=registered(agent);add_block(agent,starts)
    agent.db.get(ProjectPropertyType,row.snapshot_json['context']['property_type_id']).review_status='draft';agent.db.commit()
    before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and agent.send.await_count==before


def test_pending_reschedule_original_changed_elsewhere_closes_wait(agent):
    _,_,old,starts=book(agent)
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();agent.turn('Reschedule my visit',change('Reschedule my visit'));agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(SalesWaitRequest).one();old.meeting_time+=timedelta(hours=1);agent.db.commit();add_block(agent,starts+timedelta(days=1))
    before=agent.send.await_count;worker(agent)
    assert row.status=='closed' and old.status==MeetingStatus.CONFIRMED and agent.send.await_count==before


def test_stale_notice_does_not_resend_or_refresh_its_original_expiry(agent):
    row,starts=registered(agent);add_block(agent,starts)
    agent.send.side_effect=lambda *a,**kw:{'sid':None,'status':'failed'};worker(agent)
    assert row.status=='retry'
    row.notice_json={**row.notice_json,'expires_at':(datetime.now().astimezone()-timedelta(seconds=1)).isoformat()};due(agent,row)
    count=agent.send.await_count;worker(agent)
    assert row.status=='closed' and row.close_reason=='notice_expired' and agent.send.await_count==count


def test_mixed_material_request_does_not_expose_an_invisible_wait_question(agent):
    starts=availability(agent);product(agent,'Studio')
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure']);agent.db.commit()
    text='I want a visit and photos'
    u=Understanding.model_validate({**understanding(text,'appointment','materials',subjects={1:'photos'}).model_dump(),
        'visit':{'action':'request','evidence':'I want a visit'}})
    agent.turn(text,u)
    assert latest(agent).metadata_json.get('material_offer') and not latest(agent).metadata_json.get('wait_offer')
    agent.turn('Yes',understanding('Yes','other'))
    assert not agent.db.query(SalesWaitRequest).count()


def test_wait_migration_roundtrip_preserves_reservations():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_wait_requests.py'
    spec=importlib.util.spec_from_file_location('wait_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        for table in ['companies','projects','sales_conversations','leads','sales_messages']:connection.execute(text(f'CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE meetings (id VARCHAR(36) PRIMARY KEY, value TEXT)'))
        connection.execute(text("INSERT INTO meetings VALUES ('old','unchanged')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade();assert 'sales_wait_requests' in inspect(connection).get_table_names()
            module.downgrade();assert 'sales_wait_requests' not in inspect(connection).get_table_names()
            assert connection.execute(text('SELECT value FROM meetings')).scalar()=='unchanged'
    engine.dispose()


def test_wait_migration_generates_postgres_uniqueness_and_no_meeting_writes():
    import importlib.util,io
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261108_sales_wait_requests.py'
    spec=importlib.util.spec_from_file_location('wait_sql',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})):module.upgrade()
    sql=output.getvalue()
    assert 'UNIQUE (active_key)' in sql and 'CREATE TABLE sales_wait_requests' in sql
    assert 'UPDATE meetings' not in sql and 'DELETE' not in sql.replace('ON DELETE CASCADE','').replace('ON DELETE SET NULL','')


def test_bounded_wait_checks_rotate_across_entire_requested_range(agent):
    starts=availability(agent);product(agent,'Studio')
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();first=starts.date().isoformat();last=(starts+timedelta(days=30)).date().isoformat()
    text=f'I want a visit from {first} to {last}'
    agent.turn(text,visit(text,timing={'date_from_evidence':first,'date_until_evidence':last}))
    agent.turn('Yes',understanding('Yes','other'));row=agent.db.query(SalesWaitRequest).one()
    add_block(agent,starts+timedelta(days=20));before=agent.send.await_count;worker(agent)
    assert row.status=='waiting' and row.scan_date and agent.send.await_count==before
    due(agent,row);worker(agent)
    assert row.status=='notified',row.last_error
    assert all(datetime.fromisoformat(o['starts_at']).date()>=(starts+timedelta(days=14)).date() for o in row.notice_json['options'])
    assert row.snapshot_json['preferences']['date_from']==first and row.snapshot_json['preferences']['date_until']==last


def test_scope_revoked_at_last_dispatch_boundary_never_sends(agent,monkeypatch):
    row,starts=registered(agent);add_block(agent,starts);original=wait_service.authorize_part;before=agent.send.await_count
    def revoked(db,conversation,lead,metadata,content,**kw):
        if kw.get('before_provider'):monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS','')
        return original(db,conversation,lead,metadata,content,**kw)
    with patch.object(wait_service,'authorize_part',side_effect=revoked):worker(agent)
    assert row.status=='closed' and agent.send.await_count==before


def test_explicitly_changed_visit_preferences_close_old_wait(agent):
    row,starts=registered(agent)
    agent.turn('I want a visit at 4 PM',visit('I want a visit at 4 PM',timing={'time_from_evidence':'4 PM','time_relation':'exact'}))
    assert row.status=='closed' and row.close_reason=='preferences_changed'
    assert not agent.db.query(Meeting).count()


def test_replacement_interest_changes_close_old_wait_even_when_commercial_interest_stays(agent):
    _,_,old,starts=book(agent);product(agent,'Loft')
    for block in agent.db.query(SalesAvailabilityBlock).all():agent.db.delete(block)
    agent.db.commit();agent.turn('Reschedule my visit',change('Reschedule my visit'));agent.turn('Yes',understanding('Yes','other'))
    row=agent.db.query(SalesWaitRequest).one()
    agent.turn('Reschedule my visit to Loft',change('Reschedule my visit to Loft',target_property='Loft'))
    assert row.status=='closed' and row.close_reason=='preferences_changed' and old.status==MeetingStatus.CONFIRMED


def test_explicit_notify_after_interest_changed_does_not_save_or_promise_stale_preferences(agent):
    offer(agent);product(agent,'Loft')
    text='Tell me about Loft';agent.turn(text,typed(text,[req('p','property_details',text,ref='p')],[ref('p','property','Loft')]))
    agent.turn('Notify me if a time becomes available',wait('Notify me if a time becomes available'))
    assert not agent.db.query(SalesWaitRequest).count() and 'request is saved' not in latest(agent).content
    assert 'updated preferences' in latest(agent).content
