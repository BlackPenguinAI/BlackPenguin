"""SA07/08: durable takeover receipts and independent inactivity episodes."""
import asyncio
from datetime import datetime,timedelta
from unittest.mock import patch
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import create_engine,inspect,text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_active_integration import understanding
from test_sales_ai_group_c import product
from test_sales_conversation_review import administrator
from app.modules.sales_agent import continuity as c,live_service as live
from app.modules.sales_agent.models import SalesMessage,SalesInboundJob,SalesFollowUpJob,AgentRun
from app.modules.sales_agent.service import set_conversation_action
from app.modules.sales_agent.dialogue_store import load
from app.modules.sales_agent.turn_context import latest_outbound
from app.modules.sales_crm.models import Meeting


def action(a,value):return set_conversation_action(a.db,company_id=a.company.id,conversation_id=a.conversation.id,action=value)


def incoming(a,value):
    message=SalesMessage(conversation_id=a.conversation.id,channel=a.conversation.channel,direction='inbound',role='user',content=value,status='received')
    a.db.add(message);a.db.flush();c.received(a.db,a.conversation,message);a.db.commit();return message


def job(a,kind):return a.db.query(SalesFollowUpJob).filter_by(kind=kind,status='pending').one()


def execute(a,value,*,at=None):
    value.status='processing';value.claimed_at=datetime.utcnow();a.db.commit()
    with a.patched():
        if at:
            with patch.object(c,'clock',return_value=at),patch.object(live,'workflow_now',return_value=at):asyncio.run(c.process(a.db,value))
        else:asyncio.run(c.process(a.db,value))
    a.db.expire_all();return a.db.get(SalesFollowUpJob,value.id)


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_resume_combines_pending_once_without_historical_replay(agent,channel):
    agent.conversation.channel=channel;agent.db.commit();product(agent,'Studio')
    action(agent,'pause');m1=incoming(agent,'Show available homes');m2=incoming(agent,'What do they cost')
    old=incoming(agent,'Already answered');old.metadata_json={**old.metadata_json,'awaiting_resume':False,'handled_by_message_id':'historic'};agent.db.commit()
    action(agent,'resume');work=job(agent,'resume');assert work.payload_json['input_message_ids']==[m1.id,m2.id]
    action(agent,'resume');assert agent.db.query(SalesFollowUpJob).filter_by(kind='resume',status='pending').count()==1
    u=understanding(m1.content,'inventory','pricing').model_dump(mode='json');u['requests'][1]['evidence']=m2.content
    agent.infer.return_value=__import__('json').dumps(u)
    work=execute(agent,work);assert work.status=='processed'
    internal=agent.db.get(SalesMessage,work.payload_json['context_message_id'])
    assert internal.content==m1.content+'\n\n'+m2.content and internal.metadata_json['source_message_ids']==[m1.id,m2.id]
    assert not c.pending(agent.db,agent.conversation) and agent.send.await_count==1
    assert agent.db.get(SalesMessage,m1.id).metadata_json['handled_by_message_id']
    execute(agent,work);assert agent.send.await_count==1 and agent.infer.await_count==1 and agent.db.query(Meeting).count()==0


def test_accepted_manual_response_waits_for_lead_but_failed_send_does_not(agent):
    actor=administrator(agent);action(agent,'pause');source=incoming(agent,'Show available homes')
    agent.send.side_effect=RuntimeError('provider unavailable')
    with agent.patched(),pytest.raises(RuntimeError):asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='I can help with that.'))
    assert c.pending(agent.db,agent.conversation)==[source]
    agent.send.side_effect=lambda *a,**k:{'sid':'manual-ok','status':'sent'}
    with agent.patched():sent=asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='Here is the information you requested.'))
    assert c.accepted(sent) and not c.pending(agent.db,agent.conversation)
    action(agent,'resume');assert not agent.db.query(SalesFollowUpJob).filter_by(kind='resume',status='pending').count()
    assert c.state(agent.conversation)['waiting_for_lead'];assert job(agent,'inactivity')


def test_new_message_during_manual_send_remains_unanswered(agent):
    actor=administrator(agent);action(agent,'pause');first=incoming(agent,'Show homes')
    async def provider(*args,**kwargs):
        incoming(agent,'Also send plans');return {'sid':'manual-ok','status':'sent'}
    agent.send.side_effect=provider
    with agent.patched():asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='Here are the homes.'))
    assert [m.content for m in c.pending(agent.db,agent.conversation)]==['Also send plans']
    assert agent.db.get(SalesMessage,first.id).metadata_json['handled_by_message_id']
    action(agent,'resume');assert len(job(agent,'resume').payload_json['input_message_ids'])==1


def test_inbound_supersedes_prepared_resume_and_preserves_all_inputs(agent):
    action(agent,'pause');one=incoming(agent,'Show homes');action(agent,'resume');first=job(agent,'resume')
    two=incoming(agent,'Send plans too');agent.db.refresh(first)
    assert first.status=='cancelled' and job(agent,'resume').payload_json['input_message_ids']==[one.id,two.id]
    execute(agent,first);assert not agent.send.await_count


def test_epoch_barrier_prevents_old_turn_dispatch_after_pause_and_resume(agent):
    old=c.epoch(agent.conversation);action(agent,'pause');action(agent,'resume')
    with pytest.raises(PermissionError):c.check_epoch(agent.conversation,old)


def test_old_offers_are_not_assent_after_takeover(agent):
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'))
    assert latest_outbound(agent.db,agent.conversation.id)
    action(agent,'pause');action(agent,'resume')
    assert latest_outbound(agent.db,agent.conversation.id) is None and not load(agent.db,agent.scope)[1].offers
    agent.turn('yes',understanding('yes','other'));assert not agent.db.query(Meeting).count()


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_inactivity_once_and_responsive_to_new_message(agent,channel):
    agent.conversation.channel=channel;agent.db.commit();product(agent,'Studio')
    agent.turn('Show homes',understanding('Show homes','catalog'));closing=job(agent,'inactivity')
    assert closing.scheduled_at>=datetime.utcnow()+timedelta(minutes=44)
    done=execute(agent,closing,at=closing.scheduled_at);assert done.status=='processed' and c.CLOSING in agent.reply()
    count=agent.send.await_count;execute(agent,done,at=done.scheduled_at)
    assert agent.send.await_count==count and not agent.conversation.is_paused and not agent.lead.is_opt_out and not agent.db.query(Meeting).count()
    agent.turn('What homes are available',understanding('What homes are available','catalog'));assert job(agent,'inactivity').id!=closing.id


@pytest.mark.parametrize('block',['pause','optout','expired','quiet','pending','consent','revoked_response'])
def test_inactivity_is_omitted_when_no_longer_timely_or_allowed(agent,block):
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'));closing=job(agent,'inactivity');due=closing.scheduled_at
    context=patch('app.modules.governance.services.next_allowed_proactive_time',side_effect=lambda *a,**k:k['now'])
    if block=='pause':action(agent,'pause')
    elif block=='optout':agent.lead.is_opt_out=True
    elif block=='expired':due+=timedelta(hours=2)
    elif block=='quiet':context=patch('app.modules.governance.services.next_allowed_proactive_time',return_value=due+timedelta(days=1))
    elif block=='pending':
        row=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='New question',status='received');agent.db.add(row);agent.db.flush();agent.db.add(SalesInboundJob(conversation_id=agent.conversation.id,message_id=row.id,status='pending'))
    elif block=='consent':agent.lead.consent_status='withdrawn'
    else:agent.db.get(SalesMessage,closing.payload_json['response_message_id']).status='undelivered'
    agent.db.commit();count=agent.send.await_count
    with context:execute(agent,closing,at=due)
    assert agent.send.await_count==count and closing.status=='cancelled'


def test_new_inbound_cancels_old_closing_and_does_not_cancel_cadence(agent):
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'));closing=job(agent,'inactivity')
    nurture=SalesFollowUpJob(conversation_id=agent.conversation.id,kind='cadence',reason='warm_cadence',idempotency_key='cadence',scheduled_at=datetime.utcnow()+timedelta(hours=72));agent.db.add(nurture);agent.db.commit()
    incoming(agent,'What is the price');agent.db.refresh(closing);assert closing.status=='cancelled' and nurture.status=='pending'


def test_configurable_closing_is_separate_from_published_cadence(agent):
    agent.config.agent_ventas={**agent.config.agent_ventas,'cadence_config':{'inactivity_minutes':12,'hot_hours':8,'warm_hours':16,'cold_hours':48}};agent.db.commit()
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'))
    closing=job(agent,'inactivity');response=agent.db.get(SalesMessage,closing.payload_json['response_message_id']);assert closing.scheduled_at==response.created_at+timedelta(minutes=12)
    action(agent,'pause');actor=administrator(agent)
    with agent.patched():asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='Let me know when you are ready.'))
    action(agent,'resume');nurture=job(agent,'cadence');assert nurture.reason.endswith('_cadence') and nurture.scheduled_at>datetime.utcnow()+timedelta(hours=7)


def test_resume_evidence_cannot_span_original_messages(agent):
    action(agent,'pause');one=incoming(agent,'Show homes');two=incoming(agent,'Send plans');action(agent,'resume');work=job(agent,'resume')
    agent.infer.return_value=understanding(one.content+'\n\n'+two.content,'catalog').model_dump_json()
    result=execute(agent,work);assert result.status=='review' and agent.infer.await_count==2
    run=agent.db.query(AgentRun).filter_by(event_id='resume:'+work.id).one();assert run.error_code=='understanding_validation_failed' and len(c.pending(agent.db,agent.conversation))==2


def test_scope_change_cancels_old_jobs_without_replaying_another_lead(agent):
    action(agent,'pause');incoming(agent,'Show homes');action(agent,'resume');work=job(agent,'resume')
    work.payload_json={**work.payload_json,'lead_id':'another-lead'};agent.db.commit();assert execute(agent,work).status=='cancelled' and not agent.infer.await_count


def test_migration_is_additive_and_downgrade_does_not_turn_closings_into_nurture():
    engine=create_engine('sqlite://');connection=engine.connect();connection.execute(text('CREATE TABLE sales_conversations (id VARCHAR(36) PRIMARY KEY)'));connection.execute(text('CREATE TABLE sales_follow_up_jobs (id VARCHAR(36) PRIMARY KEY, status VARCHAR(30))'))
    path=Path(__file__).resolve().parents[1]/'alembic/versions/20261109_sales_continuity.py';spec=importlib.util.spec_from_file_location('continuity_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade();connection.execute(text("INSERT INTO sales_follow_up_jobs(id,status,kind) VALUES ('a','pending','inactivity'),('b','pending','cadence')"));module.downgrade()
    assert connection.execute(text('SELECT id FROM sales_follow_up_jobs')).scalars().all()==['b'];assert 'continuity_json' not in {r['name'] for r in inspect(connection).get_columns('sales_conversations')}


def test_late_manual_delivery_failure_reopens_only_its_receipted_messages(agent):
    actor=administrator(agent);action(agent,'pause');original=incoming(agent,'Show homes')
    with agent.patched():sent=asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='I can help.'))
    sent.status='undelivered';agent.db.commit()
    action(agent,'resume');assert job(agent,'resume').payload_json['input_message_ids']==[original.id]


def test_new_pause_during_interpretation_supersedes_resume_without_effects(agent):
    product(agent,'Studio');action(agent,'pause');incoming(agent,'Show homes');action(agent,'resume');work=job(agent,'resume')
    async def inference(*args):
        action(agent,'pause');action(agent,'resume')
        return understanding('Show homes','catalog').model_dump_json()
    agent.infer.side_effect=inference
    execute(agent,work)
    assert agent.send.await_count==0 and agent.db.query(Meeting).count()==0
    assert agent.db.query(SalesFollowUpJob).filter_by(kind='resume',status='pending').count()==1


def test_received_provider_messages_are_saved_while_paused_and_stop_is_queued(agent):
    from fastapi import BackgroundTasks
    from app.modules.sales_agent.provider_router import _record_inbound
    action(agent,'pause')
    with patch('app.modules.sales_agent.provider_router.resolve_inbound_conversation',return_value=agent.conversation):
        for i,value in enumerate(['Show homes','STOP']):
            _record_inbound(agent.db,provider='telnyx',event_id='inbound-'+str(i),to_number='+15550000000',from_number=agent.lead.phone,body=value,payload={},background_tasks=BackgroundTasks())
    assert len(c.pending(agent.db,agent.conversation))==2
    assert agent.db.query(SalesInboundJob).count()==1
    assert agent.db.get(SalesMessage,agent.db.query(SalesInboundJob).one().message_id).content=='STOP'


def test_worker_distinguishes_paused_job_from_answered_inbound(agent):
    source=incoming(agent,'Show homes');work=SalesInboundJob(conversation_id=agent.conversation.id,message_id=source.id,status='processing');agent.db.add(work);agent.db.commit();action(agent,'pause')
    work.status='processing';agent.db.commit()
    with agent.patched():asyncio.run(live.process_live_inbound_job(work.id))
    agent.db.refresh(work);assert work.status=='awaiting_resume' and source.metadata_json['agent_turn_status']=='awaiting_resume'
    assert not agent.send.await_count


def test_inactivity_virtual_clock_uses_in_app_delivery_and_does_not_enqueue_itself(agent):
    from app.modules.sales_agent.execution import sandbox
    from app.modules.sales_agent.models import OutboundMessage
    agent.conversation.channel='simulation';agent.lead.is_demo=True;agent.lead.consent_status='granted_simulation';agent.db.commit();product(agent,'Studio')
    with sandbox(agent.db,agent.conversation,datetime.utcnow()):agent.turn('Show homes',understanding('Show homes','catalog'))
    closing=job(agent,'inactivity');closing.status='processing';agent.db.commit()
    with sandbox(agent.db,agent.conversation,closing.scheduled_at):asyncio.run(c.process(agent.db,closing))
    assert closing.status=='processed' and c.CLOSING in agent.reply()
    assert agent.db.query(OutboundMessage).count()==0 and agent.send.await_count==0
    assert agent.db.query(SalesFollowUpJob).filter_by(kind='inactivity').count()==1


def test_resume_does_not_schedule_an_overdue_farewell_days_later(agent):
    actor=administrator(agent);action(agent,'pause');incoming(agent,'Show homes')
    with agent.patched():sent=asyncio.run(live.send_manual_message(agent.db,conversation_id=agent.conversation.id,company_id=agent.company.id,user_id=actor.id,content='I can help.'))
    sent.created_at=datetime.utcnow()-timedelta(days=3);agent.db.commit();action(agent,'resume')
    assert not agent.db.query(SalesFollowUpJob).filter_by(kind='inactivity',status='pending').count()


def test_mirror_exposes_receipts_summary_and_separate_jobs(agent):
    from app.modules.sales_agent.operational_context import snapshot
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'))
    action(agent,'pause');incoming(agent,'Send floor plans');action(agent,'resume')
    context=snapshot(agent.db,agent.conversation,allowed_projects={agent.project.id})
    assert context['continuity']['pending_message_count']==1
    assert context['continuity']['jobs'][0]['kind']=='resume'
    assert context['handoff_summary']['pending_messages']==1
    limited=snapshot(agent.db,agent.conversation,allowed_projects={agent.project.id},scope_limited=True)
    assert limited['continuity'] is None and limited['handoff_summary'] is None


@pytest.mark.parametrize('minutes',[True,0,4,241,1.2,'45'])
def test_inactivity_configuration_rejects_invalid_minutes(agent,minutes):
    from app.modules.ai_core.services import validate_sales_configuration
    from fastapi import HTTPException
    with pytest.raises(HTTPException):validate_sales_configuration({**agent.config.agent_ventas,'cadence_config':{'inactivity_minutes':minutes}})


def test_repeated_resume_never_sends_a_second_closing_for_the_same_exchange(agent):
    product(agent,'Studio');agent.turn('Show homes',understanding('Show homes','catalog'));closing=job(agent,'inactivity');due=closing.scheduled_at
    execute(agent,closing,at=due)
    with patch.object(c,'clock',return_value=due+timedelta(minutes=1)):
        action(agent,'pause');action(agent,'resume')
    assert not agent.db.query(SalesFollowUpJob).filter_by(kind='inactivity',status='pending').count()


def test_old_inbound_worker_cannot_replay_a_message_owned_by_resume(agent):
    original=incoming(agent,'Show homes');queued=SalesInboundJob(conversation_id=agent.conversation.id,message_id=original.id,status='processing');agent.db.add(queued);agent.db.commit()
    action(agent,'pause');action(agent,'resume')
    with agent.patched():asyncio.run(live.process_live_inbound(agent.conversation.id,original.id))
    assert agent.infer.await_count==0 and agent.send.await_count==0 and job(agent,'resume')


def test_stale_internal_context_cannot_be_reinterpreted_under_a_new_epoch(agent):
    internal=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='yes',status='internal',metadata_json={'resume_context':True,'continuity_epoch':c.epoch(agent.conversation),'source_message_ids':[]})
    agent.db.add(internal);agent.db.commit();action(agent,'pause');action(agent,'resume')
    with agent.patched():asyncio.run(live.process_live_inbound(agent.conversation.id,internal.id))
    assert not agent.infer.await_count and not agent.send.await_count


def test_internal_consolidation_does_not_inflate_engagement(agent):
    original=incoming(agent,'Show homes')
    internal=SalesMessage(direction='inbound',role='user',content='Show homes',metadata_json={'resume_context':True})
    assert live._lead_intelligence_input([original,internal])==('Show homes',1)


def test_cadence_does_not_compete_with_unanswered_takeover_messages(agent):
    incoming(agent,'Show homes');agent.conversation.is_paused=True;agent.db.commit();original=incoming(agent,'Send plans');agent.conversation.is_paused=False
    nurture=SalesFollowUpJob(conversation_id=agent.conversation.id,kind='cadence',reason='warm_cadence',status='processing',idempotency_key='cadence-pending',scheduled_at=datetime.utcnow());agent.db.add(nurture);agent.db.commit()
    with agent.patched():asyncio.run(live.process_live_followup_job(nurture.id))
    agent.db.refresh(nurture);assert nurture.status=='cancelled' and not agent.send.await_count


def test_paused_conversation_is_blocked_at_the_actual_provider_boundary(agent):
    action(agent,'pause')
    with agent.patched(),pytest.raises(PermissionError):asyncio.run(live._dispatch(agent.db,conversation=agent.conversation,lead=agent.lead,content='Here are the homes.',role='assistant',agent_run_id=None))
    assert not agent.send.await_count


def test_resumed_profile_facts_keep_original_message_provenance(agent):
    from app.modules.sales_agent.lead_profile import resolve
    action(agent,'pause');first=incoming(agent,'My budget is USD 450,000');second=incoming(agent,'I need three bedrooms');action(agent,'resume');work=job(agent,'resume')
    u=understanding(first.content,'other').model_dump(mode='json');u['preferences']=[{'key':'budget','value':'USD 450,000','evidence':first.content,'status':'declared'},{'key':'bedrooms','value':'3','evidence':second.content,'status':'declared'}]
    agent.infer.return_value=__import__('json').dumps(u);assert execute(agent,work).status=='processed'
    profile=resolve(agent.lead)['current']
    assert profile['budget']['source_ref']['message_id']==first.id
    assert profile['bedrooms']['source_ref']['message_id']==second.id
    assert profile['budget']['source_ref']['resume_context_id']==work.payload_json['context_message_id']


def test_uncertain_resume_send_requires_review_without_automatic_resend(agent):
    action(agent,'pause');original=incoming(agent,'Show homes');action(agent,'resume');work=job(agent,'resume');work.status='processing';agent.db.commit();product(agent,'Studio')
    agent.infer.return_value=understanding(original.content,'catalog').model_dump_json();agent.send.side_effect=lambda *args,**kwargs:{'status':'queued'}
    with agent.patched(),pytest.raises(RuntimeError):asyncio.run(live.process_live_followup_job(work.id))
    agent.db.refresh(work);assert work.status=='review' and len(c.pending(agent.db,agent.conversation))==1
    count=agent.send.await_count
    with agent.patched():asyncio.run(live.process_live_followup_job(work.id))
    assert agent.send.await_count==count
