"""HEI-03B.5 real ORM / shared dispatcher; no network or real lead data."""
import asyncio
from datetime import timedelta
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_bp_hei03b3_worker_delivery import real_lane, run


def claim(l,kind):
    from app.modules.sales_agent.models import SalesFollowUpJob
    from app.modules.sales_agent.engine_router import event_scope
    from app.modules.hermes_sales_core.scheduled_work import now
    job=l.db.query(SalesFollowUpJob).filter_by(kind=kind).one()
    conv=l.db.get(l.Conversation,'conversation')
    event={'cadence':'followup','inactivity':'inactivity','resume':'resume'}[kind]+':'+job.id
    job.payload_json={**job.payload_json,'sales_engine_pin':{**event_scope(conv,event),'engine':'hermes','policy_version_id':'version'}}
    job.status='processing';job.scheduled_at=now()-timedelta(seconds=1);job.claimed_at=now();l.db.commit()
    return job.id


def schedule(l,kind='inactivity'):
    run(l)
    return claim(l,kind)


def execute(l,jid):
    from app.modules.hermes_sales_core.scheduled_work import run_scheduled
    return asyncio.run(run_scheduled(l.db,jid))


def follow(l,jid):
    from app.modules.sales_agent.models import SalesFollowUpJob
    return l.db.get(SalesFollowUpJob,jid)


def test_finished_reply_schedules_two_scoped_jobs(real_lane):
    from app.modules.sales_agent.models import SalesFollowUpJob
    l=real_lane;run(l)
    jobs=l.db.query(SalesFollowUpJob).all()
    assert {j.kind for j in jobs}=={'inactivity','cadence'}
    for j in jobs:
        assert j.payload_json['lead_id']=='lead' and j.payload_json['epoch']==1
        assert j.payload_json['inbound_message_id']=='inbound'
        assert j.payload_json['response_message_id']==l.db.get(l.Message,'inbound').metadata_json['handled_by_message_id']
    assert l.db.get(l.Lead,'lead').next_action_at


def test_inactivity_uses_existing_dispatcher_without_model(real_lane):
    from app.modules.sales_agent.continuity import CLOSING,state
    l=real_lane;jid=schedule(l);execute(l,jid)
    assert l.calls[-1]==CLOSING and len(l.calls)==2 and len(l.sdk_calls)==1
    job=follow(l,jid);assert job.status=='processed'
    assert state(l.db.get(l.Conversation,'conversation'))['last_closing_message_id']==job.payload_json['receipt_message_id']
    row=l.db.get(l.Message,job.payload_json['receipt_message_id'])
    assert row.metadata_json['engine']=='hermes-scheduled/1'
    assert l.db.query(l.Run).count()==1 and l.load(l.db,l.scope).revision==1


def test_cadence_uses_deterministic_message_no_recursive_schedule(real_lane):
    from app.modules.hermes_sales_core.scheduled_work import CADENCE_REPLY
    from app.modules.sales_agent.models import SalesFollowUpJob
    l=real_lane;jid=schedule(l,'cadence');execute(l,jid)
    assert l.calls[-1]==CADENCE_REPLY and l.db.query(l.Run).count()==1
    assert follow(l,jid).status=='processed'
    assert l.db.query(SalesFollowUpJob).filter_by(kind='cadence').count()==1
    assert l.db.get(l.Lead,'lead').next_action_at is None


def test_queued_scheduled_receipt_reconciles_without_resend(real_lane):
    l=real_lane;jid=schedule(l);l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):execute(l,jid)
    row=l.db.query(l.Message).filter(l.Message.metadata_json['hermes_scheduled_job_id'].as_string()==jid).one()
    out=l.db.get(l.Out,row.metadata_json['outbound_message_id'])
    row.status=out.status='sent';l.db.commit();execute(l,jid)
    assert follow(l,jid).status=='processed' and len(l.calls)==2 and len(l.sdk_calls)==1


def test_existing_unknown_scheduled_outbox_never_resends(real_lane):
    l=real_lane;jid=schedule(l);l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):execute(l,jid)
    row=l.db.query(l.Message).filter(l.Message.metadata_json['hermes_scheduled_job_id'].as_string()==jid).one()
    out=l.db.get(l.Out,row.metadata_json['outbound_message_id']);row.status=out.status='delivery_unknown';l.db.commit()
    with pytest.raises(PermissionError):execute(l,jid)
    assert len(l.calls)==2


@pytest.mark.parametrize('case',['epoch','optout','paused','new_inbound','wrong_scope','expired','unscoped','switch'])
def test_stale_or_unauthorized_scheduled_job_does_not_send(real_lane,case):
    from app.modules.hermes_sales_core.scheduled_work import now
    from app.modules.hermes_sales_core.staff_models import HermesGlobalSettings
    l=real_lane;jid=schedule(l);c=l.db.get(l.Conversation,'conversation');lead=l.db.get(l.Lead,'lead');job=follow(l,jid)
    if case=='epoch':c.continuity_json={**c.continuity_json,'epoch':2}
    elif case=='optout':lead.is_opt_out=True
    elif case=='paused':c.is_paused=True
    elif case=='new_inbound':c.continuity_json={**c.continuity_json,'last_inbound_message_id':'new'}
    elif case=='wrong_scope':job.payload_json={**job.payload_json,'lead_id':'other'}
    elif case=='expired':job.payload_json={**job.payload_json,'expires_at':(now()-timedelta(seconds=1)).isoformat()}
    elif case=='unscoped':job.payload_json={**job.payload_json,'hermes_scheduled':False}
    else:
        cfg=l.db.get(HermesGlobalSettings,'global');cfg.configuration={**cfg.configuration,'active_sales_engine':'langgraph'}
    l.db.commit()
    with pytest.raises(PermissionError):execute(l,jid)
    assert len(l.calls)==1


def test_pending_buyer_blocks_cadence(real_lane):
    l=real_lane;jid=schedule(l,'cadence');l.db.get(l.Job,'job').status='review';l.db.commit()
    with pytest.raises(PermissionError):execute(l,jid)
    assert len(l.calls)==1


def test_scheduled_authorization_rechecked_immediately_before_provider(real_lane,monkeypatch):
    from app.modules.hermes_sales_core import scheduled_work as sw
    l=real_lane;jid=schedule(l);original=sw.authorize_scheduled;checks=[]
    def check(*args,**kwargs):
        checks.append(1)
        if len(checks)==2:raise PermissionError('revoked before provider')
        return original(*args,**kwargs)
    monkeypatch.setattr(sw,'authorize_scheduled',check)
    with pytest.raises(PermissionError):execute(l,jid)
    assert len(checks)==2 and len(l.calls)==1
    assert l.db.query(l.Out).filter_by(idempotency_key='hermes:scheduled:'+jid).one().status=='failed'


def resume(l):
    from app.modules.sales_agent import continuity
    msg=l.db.get(l.Message,'inbound');msg.metadata_json={**msg.metadata_json,'awaiting_resume':True}
    l.db.get(l.Job,'job').status='awaiting_resume'
    l.db.flush();conv=l.db.get(l.Conversation,'conversation');continuity.queue_resume(l.db,conv);l.db.commit()
    return claim(l,'resume')


def test_resume_requeues_original_without_fabricated_message(real_lane):
    l=real_lane;jid=resume(l);original=l.db.get(l.Message,'inbound').provider_message_id
    execute(l,jid)
    assert follow(l,jid).status=='processed' and follow(l,jid).reason=='hermes_resume_requeued'
    assert l.db.get(l.Job,'job').status=='pending'
    inbound=l.db.get(l.Message,'inbound');assert inbound.provider_message_id==original and not inbound.metadata_json['awaiting_resume']
    assert l.db.query(l.Message).count()==1 and l.db.query(l.Run).count()==0 and not l.calls
    l.db.get(l.Job,'job').status='processing';l.db.commit();run(l)
    assert l.db.get(l.Job,'job').status=='processed' and len(l.calls)==len(l.sdk_calls)==1


@pytest.mark.parametrize('case',['legacy_pin','previous_run','missing_provider','previous_outbox','stop','multiple'])
def test_resume_requires_untouched_single_authenticated_inbound(real_lane,case):
    from app.modules.hermes_sales_core.scheduled_work import now
    l=real_lane;jid=resume(l);msg=l.db.get(l.Message,'inbound');job=follow(l,jid)
    if case=='legacy_pin':msg.metadata_json={**msg.metadata_json,'sales_engine_pin':{**msg.metadata_json['sales_engine_pin'],'engine':'langgraph'}}
    elif case=='previous_run':l.db.add(l.Run(conversation_id='conversation',event_id='telnyx:provider-in',mode='live',status='failed',graph_version='hermes/live/1',toolset_version='hermes-tools/1.0',model='test',prompt_snapshot={}))
    elif case=='missing_provider':msg.provider_message_id=None
    elif case=='previous_outbox':l.db.add(l.Out(conversation_id='conversation',idempotency_key='previous',channel='sms',provider='telnyx',content='uncertain',status='delivery_unknown'))
    elif case=='stop':msg.content='STOP'
    else:
        l.db.add(l.Message(id='other',conversation_id='conversation',channel='sms',direction='inbound',role='user',content='Another question',status='received',provider_message_id='other-provider',created_at=msg.created_at-timedelta(seconds=1),metadata_json={'lead_id':'lead','project_id':'project','awaiting_resume':True,'continuity_recorded':True}))
        job.payload_json={**job.payload_json,'input_message_ids':['other','inbound']}
    l.db.commit()
    with pytest.raises(PermissionError):execute(l,jid)
    assert l.db.get(l.Job,'job').status=='awaiting_resume' and not l.calls


def test_takeover_clears_authorization_but_not_permanent_preferences(real_lane):
    from app.modules.hermes_sales_core.scheduled_work import invalidate_boundary
    l=real_lane;conv=l.db.get(l.Conversation,'conversation')
    conv.continuity_json={**conv.continuity_json,'epoch':2,'offer_barrier':True}
    state={'search_preferences':{'budget':300000},'conversation_focus':{'unit_id':'test'},
           'last_slot_search':{'proposal_id':'old'},'last_presented_choice_set':{'type':'property'},
           'confirmation_request':{'status':'awaiting_confirmation'},'visit_draft':{'status':'selected'},'offered_assets':{'pending_request':{'id':'x'}}}
    assert invalidate_boundary(state,SimpleNamespace(metadata_json={'engine':'hermes-agent','continuity_epoch':1}),conv)
    assert state['search_preferences']=={'budget':300000} and state['conversation_focus']=={'unit_id':'test'}
    assert state['confirmation_request'] is None and state['last_slot_search'] is None and state['offered_assets']=={}
    assert state['visit_draft']['status']=='idle'


def test_current_epoch_preserves_valid_offers(real_lane):
    from app.modules.hermes_sales_core.scheduled_work import invalidate_boundary
    l=real_lane;conv=l.db.get(l.Conversation,'conversation');s={'last_slot_search':{'proposal_id':'current'}}
    assert not invalidate_boundary(s,SimpleNamespace(metadata_json={'engine':'hermes-agent','continuity_epoch':1}),conv)
    assert s['last_slot_search']['proposal_id']=='current'


def test_resume_creates_missing_job_for_existing_paused_provider_message(real_lane):
    from app.modules.sales_agent import continuity
    l=real_lane;msg=l.db.get(l.Message,'inbound');msg.metadata_json={**msg.metadata_json,'awaiting_resume':True}
    l.db.delete(l.db.get(l.Job,'job'));l.db.flush()
    conv=l.db.get(l.Conversation,'conversation');continuity.queue_resume(l.db,conv);l.db.commit()
    jid=claim(l,'resume');execute(l,jid)
    original=l.db.query(l.Job).filter_by(message_id='inbound').one()
    assert original.status=='pending' and original.attempt_number==0
    assert l.db.query(l.Message).count()==1 and msg.provider_message_id=='provider-in'
    assert follow(l,jid).payload_json['requeued_inbound_job_id']==original.id


def test_queue_resume_includes_new_pending_input_with_autoflush_off(real_lane):
    from app.modules.sales_agent import continuity
    l=real_lane;msg=l.db.get(l.Message,'inbound');msg.metadata_json={**msg.metadata_json,'awaiting_resume':True}
    # No explicit flush here: production SessionLocal disables autoflush.
    job=continuity.queue_resume(l.db,l.db.get(l.Conversation,'conversation'))
    assert job is not None and job.payload_json['input_message_ids']==['inbound']
