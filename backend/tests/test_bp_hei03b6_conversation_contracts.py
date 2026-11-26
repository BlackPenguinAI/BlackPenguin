"""Real ORM and dispatcher; test-only readiness, fake SDK/provider, SQLite."""
from datetime import timedelta
import pytest
from test_bp_hei03b3_worker_delivery import real_lane, run
from test_bp_hei03b5_scheduled_work import resume, execute, follow


def batch(l, *, prior_job=False):
    msg=l.db.get(l.Message,'inbound')
    l.db.add(l.Message(id='other',conversation_id='conversation',channel='sms',direction='inbound',role='user',
        content='I like the first property.',status='received',provider_message_id='other-provider',
        created_at=msg.created_at-timedelta(seconds=1),metadata_json={'lead_id':'lead','project_id':'project',
            'awaiting_resume':True,'continuity_recorded':True}))
    if prior_job:l.db.add(l.Job(id='prior-job',conversation_id='conversation',message_id='other',status='awaiting_resume'))
    l.db.flush(); jid=resume(l)
    execute(l,jid)
    l.db.get(l.Job,'job').status='processing';l.db.commit()
    return jid

@pytest.mark.parametrize('prior_job',[False,True])
def test_original_batch_handled_by_one_accepted_response(real_lane,prior_job):
    l=real_lane;jid=batch(l,prior_job=prior_job)
    assert l.db.query(l.Message).count()==2 and follow(l,jid).status=='processed'
    run(l)
    assert len(l.sdk_calls)==len(l.calls)==1 and l.db.query(l.Run).count()==1
    a=l.db.get(l.Message,'inbound');b=l.db.get(l.Message,'other')
    assert a.provider_message_id=='provider-in' and b.provider_message_id=='other-provider'
    assert a.metadata_json['handled_by_message_id']==b.metadata_json['handled_by_message_id']
    final=l.db.get(l.Message,a.metadata_json['handled_by_message_id'])
    assert final.metadata_json['handled_inbound_message_ids']==['other','inbound']
    assert not b.metadata_json['awaiting_resume']
    assert l.db.query(l.Run).one().input_snapshot['hermes_resume_batch']['anchor_id']=='inbound'
    if prior_job:assert l.db.get(l.Job,'prior-job').status=='superseded'

@pytest.mark.parametrize('change',['content','provider','scope','epoch','newer','handled'])
def test_released_batch_revalidates_every_original(real_lane,change):
    l=real_lane;batch(l);row=l.db.get(l.Message,'other');c=l.db.get(l.Conversation,'conversation')
    if change=='content':row.content='Changed'
    elif change=='provider':row.provider_message_id='changed'
    elif change=='scope':row.metadata_json={**row.metadata_json,'lead_id':'wrong'}
    elif change=='epoch':c.continuity_json={**c.continuity_json,'epoch':999}
    elif change=='newer':c.continuity_json={**c.continuity_json,'last_inbound_message_id':'another'}
    else:row.metadata_json={**row.metadata_json,'handled_by_message_id':'manual'}
    l.db.commit()
    with pytest.raises(PermissionError):run(l)
    assert not l.calls and not l.sdk_calls


def test_batch_waits_for_accepted_receipt_before_marking_earlier_input(real_lane):
    l=real_lane;batch(l);l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):run(l)
    assert l.db.get(l.Message,'other').metadata_json['awaiting_resume']
    l.db.query(l.Out).one().status='sent';l.db.query(l.Message).filter_by(direction='outbound').one().status='sent';l.db.commit()
    run(l)
    assert not l.db.get(l.Message,'other').metadata_json['awaiting_resume']
    assert len(l.calls)==len(l.sdk_calls)==1


def long_draft(l, *, actionable=False):
    from app.modules.hermes_sales_core.bp_state_store import blank_state
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    reply=('I can help with approved property information. '*23).strip()+'\n\n'+('Please ask about the property details and available features. '*20).strip()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id);state=blank_state(l.scope)
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult(reply,[],[]),state),[{'type':'property'}] if actionable else [])
        reserve_live_run(l.db,l.scope,inbound_message_id='inbound')
        persist_live_draft(l.db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);l.db.commit()
    l.prepare=prepare
    return reply


def test_multipart_informational_reply_commits_once(real_lane):
    l=real_lane;reply=long_draft(l);run(l)
    assert len(l.calls)==2 and len(l.sdk_calls)==1
    r=l.db.query(l.Run).one();meta=r.output_snapshot['metadata']
    assert r.output_snapshot['reply']==reply and len(meta['message_ids'])==2
    assert meta['message_id']==meta['message_ids'][-1] and l.load(l.db,l.scope).revision==1
    assert l.load(l.db,l.scope).data['last_assistant_reply']==reply
    assert l.db.query(l.Message).count()==3
    assert l.db.get(l.Job,'job').status=='processed'


def test_multipart_queued_group_no_partial_state_or_resend(real_lane):
    l=real_lane;long_draft(l);l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):run(l)
    assert len(l.calls)==2 and l.load(l.db,l.scope).revision==0
    for o in l.db.query(l.Out).all():o.status='sent'
    for r in l.db.query(l.Message).filter_by(direction='outbound').all():r.status='sent'
    l.db.commit();run(l)
    assert len(l.calls)==2 and len(l.sdk_calls)==1 and l.load(l.db,l.scope).revision==1


def test_multipart_actionable_menu_blocked_before_send(real_lane):
    l=real_lane;long_draft(l,actionable=True)
    with pytest.raises(PermissionError):run(l)
    assert not l.calls and l.load(l.db,l.scope).revision==0


def test_multipart_tampering_blocks_state_receipt(real_lane):
    l=real_lane;long_draft(l);l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):run(l)
    for o in l.db.query(l.Out).all():o.status='sent'
    for r in l.db.query(l.Message).filter_by(direction='outbound').all():r.status='sent'
    row=l.db.query(l.Message).filter_by(direction='outbound').first();row.content+=' changed'
    l.db.commit()
    with pytest.raises(PermissionError):run(l)
    assert len(l.calls)==2 and l.load(l.db,l.scope).revision==0


def test_external_gallery_targets_are_issued_and_revoked_on_change(real_lane,monkeypatch):
    from datetime import datetime,timezone
    from urllib.parse import urlsplit
    from app.core.config import settings
    from app.modules.projects.models import ProjectPropertyType,ProjectOnboardingSource,ProjectSourceKind,ProjectSourceStatus,ProjectSalesAsset,SalesAssetShare
    from app.modules.projects.asset_share_service import resolve
    from app.modules.hermes_sales_core.bp_state_store import blank_state
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from fastapi import HTTPException
    import re
    l=real_lane;db=l.db;monkeypatch.setattr(settings,'PUBLIC_APP_URL','https://example.invalid')
    db.add(ProjectPropertyType(id='type-a',project_id='project',name='Van Buren',review_status='confirmed',bedrooms=3))
    db.get(l.Message,'inbound').content='Please send me the gallery for Van Buren.'
    source=ProjectOnboardingSource(id='source-gallery',project_id='project',kind=ProjectSourceKind.URL,status=ProjectSourceStatus.READY,name='Gallery',
        extracted_links=[{'url':'https://gallery.example.invalid/a','kind':'photos'},{'url':'https://gallery.example.invalid/b','kind':'gallery_image'},
                         {'url':'https://gallery.example.invalid/unrelated','kind':'external_reference'}, {'url':'http://127.0.0.1/private','kind':'photos'}])
    db.add(source);db.add(ProjectSalesAsset(id='asset-gallery',company_id='co',project_id='project',property_type_id='type-a',source_id=source.id,
        asset_type='gallery_image',content_tags=['gallery_image'],display_name='Van Buren Gallery',approval_status='approved',
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp']))
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id);state=blank_state(l.scope);state['conversation_focus']['property_type_id']='type-a'
        state['offered_assets']={'pending_request':{'id':'request-gallery','source_inbound_message_id':'inbound','unit_id':'type-a',
            'subject':'gallery_image','asset_ids':['asset-gallery'],'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}}
        reserve_live_run(db,l.scope,inbound_message_id='inbound')
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult('I found the requested material. I still need to validate the share before sending it.',[],[{'tool':'get_unit_media','status':'executed','error_code':None}]),state),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare;run(l)
    shares=db.query(SalesAssetShare).all();assert len(shares)==2
    assert {s.target_url for s in shares}=={'https://gallery.example.invalid/a','https://gallery.example.invalid/b'}
    tokens=re.findall(r'/projects/a/([^\s]+)',l.calls[-1]);assert len(tokens)==2
    assert 'gallery.example.invalid' not in l.calls[-1]
    assert len(l.load(db,l.scope).data['shared_media']['asset-gallery']['share_ids'])==2
    for token in tokens:assert resolve(db,token)[1].target_url in {s.target_url for s in shares}
    source=db.get(ProjectOnboardingSource,'source-gallery');source.extracted_links=[];db.commit()
    for token in tokens:
        with pytest.raises(HTTPException) as exc:resolve(db,token)
        assert exc.value.status_code==404


def test_engine_transition_preserves_facts_and_clears_legacy_offers(real_lane):
    from app.modules.hermes_sales_core.engine_boundary import transition,KEY
    from app.modules.sales_agent.dialogue_store import Scope,load,save
    from app.modules.sales_agent.continuity import epoch
    from app.modules.sales_agent.understanding_contract import Offer
    from app.modules.sales_agent.models import SalesFollowUpJob
    l=real_lane;db=l.db;c=db.get(l.Conversation,'conversation');m=db.get(l.Message,'inbound')
    pin=m.metadata_json['sales_engine_pin'];assert transition(db,c,m,pin)
    assert c.continuity_json[KEY]=='hermes' and epoch(c)==1
    scope=Scope('co','project','conversation','lead');rev,state=load(db,scope)
    # A stale transient proposal and genuine commercial preference in the old lane.
    state.booking_search={'old':True}
    save(db,scope,event_key='previous-legacy',expected_revision=rev,state=state);db.commit()
    legacy={**pin,'engine':'langgraph','policy_version_id':None,'event_id':'telnyx:next-event'}
    assert transition(db,c,m,legacy);db.flush()
    assert epoch(c)==2 and c.continuity_json[KEY]=='langgraph'
    assert load(db,scope)[1].booking_search=={} and c.continuity_json['offer_barrier']
    assert not transition(db,c,m,legacy)


def test_old_scheduled_engine_not_transferred(real_lane):
    from app.modules.hermes_sales_core.engine_boundary import check_scheduled,KEY
    l=real_lane;c=l.db.get(l.Conversation,'conversation');c.continuity_json={**c.continuity_json,KEY:'hermes'}
    with pytest.raises(ValueError):check_scheduled(c,{'engine':'langgraph'},'cadence')
    check_scheduled(c,{'engine':'hermes'},'cadence')


def test_real_preparation_includes_prior_original_as_verified_history(real_lane,monkeypatch):
    from app.modules.hermes_sales_core.live_preparation import prepare_live_turn,reserve_live_run
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    l=real_lane;batch(l)
    run_obj=reserve_live_run(l.db,l.scope,inbound_message_id='inbound');rid=run_obj.id;l.db.commit()
    calls=[]
    def fake_runtime(self,request):
        calls.append(request)
        assert not l.db.in_transaction()
        return TurnResult('I can help with property details.',[],[])
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake_runtime)
    turn=prepare_live_turn(l.db,l.scope,inbound_message_id='inbound',run_id=rid)
    assert turn.prepared.result.reply=='I can help with property details.'
    assert calls[0].history[-1]=={'role':'user','content':'I like the first property.'}
    assert calls[0].message=='Tell me about the property.'
    assert 'unanswered originals' in calls[0].verified_context['resume_guidance']
