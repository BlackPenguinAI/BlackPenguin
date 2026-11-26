"""Real BP ORM/dispatcher integration, isolated SQLite and fake SDK/provider.

Do not use production database or external transport. The readiness override
exists ONLY inside these tests. All real provider methods are replaced.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from copy import deepcopy

import pytest


@pytest.fixture
def real_lane(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.postgres import Base
    import app.db.base  # noqa: F401
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project,ProjectProfile
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation,SalesMessage,SalesInboundJob,AgentRun,OutboundMessage
    from app.modules.hermes_sales_core.staff_models import HermesGlobalVersion,HermesGlobalSettings
    from app.modules.hermes_sales_core.staff_config import baseline
    from app.modules.hermes_sales_core import engine_selection, live_job, provider_delivery, sdk_service
    from app.modules.sales_agent import live_service
    from app.modules.hermes_sales_core.contracts import TurnScope,TurnResult
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.bp_state_store import blank_state,load
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from app.modules.sales_agent.engine_router import event_scope
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    db=Session(engine,autoflush=False)
    scope=TurnScope('co','project','conversation','lead')
    timestamp=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=2)
    policy={**baseline(),'enabled':True}
    db.add_all([Company(id='co',name='Test Company',country_code='US',is_active=True),
        Project(id='project',company_id='co',name='Test Homes',city='Test City',country='US',timezone='America/Lima',is_active=True,is_demo=False),
        ProjectProfile(id='profile',project_id='project',final_approved=True,profile_data={},field_states={}),
        Lead(id='lead',company_id='co',project_id='project',full_name='Test Buyer',phone='+15550000001',
             consent_status='granted',is_opt_out=False,agent_status='active',is_demo=False),
        HermesGlobalVersion(id='version',version=1,configuration=policy,is_published=True,published_at=timestamp),
        HermesGlobalSettings(id='global',last_version=1,published_version_id='version',configuration={**policy,'active_sales_engine':'hermes'})])
    conversation=SalesConversation(id='conversation',company_id='co',project_id='project',lead_id='lead',
        provider='telnyx',channel='sms',is_paused=False,continuity_json={'lead_id':'lead','project_id':'project','epoch':1,'last_inbound_message_id':'inbound'})
    pin={**event_scope(conversation,'telnyx:provider-in'),'engine':'hermes','policy_version_id':'version'}
    inbound=SalesMessage(id='inbound',conversation_id='conversation',channel='sms',direction='inbound',role='user',
        content='Tell me about the property.',status='received',provider_message_id='provider-in',created_at=timestamp,
        metadata_json={'lead_id':'lead','project_id':'project','continuity_recorded':True,'sales_engine_pin':pin})
    job=SalesInboundJob(id='job',conversation_id='conversation',message_id='inbound',status='processing',attempt_number=1)
    db.add_all([conversation,inbound,job]);db.commit()
    monkeypatch.setattr(engine_selection,'live_hermes_ready',lambda:True)
    calls=[];sdk_calls=[];status=['sent']
    async def fake_provider(*args,**kwargs):
        calls.append(kwargs['body'])
        return {'sid':'provider-out-'+str(len(calls)),'status':status[0]}
    monkeypatch.setattr(live_service,'send_sms',fake_provider)
    monkeypatch.setattr(live_service,'send_message',fake_provider)
    async def prepare(job_id,run_id):
        assert not db.in_transaction(), 'API must not hold DB transaction during private SDK call'
        sdk_calls.append(run_id)
        run=reserve_live_run(db,scope,inbound_message_id='inbound')
        assert run.id==run_id
        state=blank_state(scope)
        turn=P04PreparedTurn(PreparedHermesTurn(scope,'inbound',0,TurnResult('I can help with property details.',[],[]),state),[])
        persist_live_draft(db,scope,inbound_message_id='inbound',run_id=run_id,turn=turn)
        db.commit()
    try:
        yield SimpleNamespace(db=db,scope=scope,calls=calls,sdk_calls=sdk_calls,status=status,prepare=prepare,
            job=live_job,delivery=provider_delivery,service=live_service,sdk_service=sdk_service,
            Conversation=SalesConversation,Message=SalesMessage,Job=SalesInboundJob,Lead=Lead,Run=AgentRun,Out=OutboundMessage,
            selection=engine_selection,load=load)
    finally:db.close();engine.dispose()


def run(lane):
    asyncio.run(lane.job.run_job(lane.db,'job',prepare=lane.prepare))


def test_shared_dispatcher_completes_real_orm_turn(real_lane):
    l=real_lane;run(l)
    assert l.calls==['I can help with property details.'] and len(l.sdk_calls)==1
    job=l.db.get(l.Job,'job');inbound=l.db.get(l.Message,'inbound')
    assert job.status=='processed' and inbound.metadata_json['agent_turn_status']=='answered'
    assert l.load(l.db,l.scope).revision==1
    r=l.db.query(l.Run).one();assert r.status=='completed' and r.graph_version=='hermes/live/1'
    out=l.db.query(l.Out).one();assert out.idempotency_key=='hermes:reply:'+r.id
    assert r.output_snapshot['reply']==l.calls[0]


def test_queued_receipt_polls_without_second_send_or_model(real_lane):
    l=real_lane;l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):run(l)
    l.job.mark_failure(l.db,'job',pending=True)
    assert l.db.get(l.Job,'job').status=='retry'
    assert l.load(l.db,l.scope).revision==0
    # Existing authenticated webhook state update, represented by exact rows.
    out=l.db.query(l.Out).one();out.status='sent'
    row=l.db.query(l.Message).filter_by(direction='outbound').one();row.status='sent'
    l.db.get(l.Job,'job').status='processing';l.db.commit()
    run(l)
    assert len(l.calls)==len(l.sdk_calls)==1
    assert l.db.get(l.Job,'job').status=='processed' and l.load(l.db,l.scope).revision==1


def test_changed_authorization_between_enqueue_and_send(real_lane,monkeypatch):
    l=real_lane;actual=l.delivery.authorize_part;count=[]
    def revoke(*args,**kwargs):
        count.append(1)
        if len(count)==2:raise PermissionError('changed permission')
        return actual(*args,**kwargs)
    monkeypatch.setattr(l.delivery,'authorize_part',revoke)
    with pytest.raises(PermissionError):run(l)
    l.job.mark_failure(l.db,'job')
    assert len(count)==2 and l.calls==[] and l.db.query(l.Out).one().status=='failed'
    assert l.db.get(l.Job,'job').status=='review' and l.load(l.db,l.scope).revision==0


def test_existing_unknown_outbox_requires_review(real_lane):
    l=real_lane;l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):run(l)
    out=l.db.query(l.Out).one();out.status='delivery_unknown'
    l.db.query(l.Message).filter_by(direction='outbound').one().status='delivery_unknown';l.db.commit()
    with pytest.raises(PermissionError):run(l)
    assert len(l.calls)==len(l.sdk_calls)==1


def test_stop_without_sdk_or_agent_run(real_lane):
    l=real_lane;l.db.get(l.Message,'inbound').content='STOP';l.db.commit()
    run(l)
    assert l.calls==[l.delivery.STOP_REPLY] and l.sdk_calls==[] and l.db.query(l.Run).count()==0
    lead=l.db.get(l.Lead,'lead');assert lead.is_opt_out and lead.consent_status=='opted_out'
    assert l.db.get(l.Conversation,'conversation').is_paused
    assert l.db.get(l.Job,'job').status=='processed'


def test_handoff_without_sdk_or_agent_run(real_lane):
    l=real_lane;l.db.get(l.Message,'inbound').content='I want to talk to a human.';l.db.commit()
    run(l)
    assert l.calls==[l.delivery.HANDOFF_REPLY] and l.sdk_calls==[] and l.db.query(l.Run).count()==0
    assert l.db.get(l.Lead,'lead').agent_status=='human_control'
    assert l.db.get(l.Conversation,'conversation').is_paused and l.db.get(l.Job,'job').status=='processed'


def test_readiness_gate_prevents_job_and_private_sdk(real_lane,monkeypatch):
    l=real_lane;monkeypatch.setattr(l.selection,'live_hermes_ready',lambda:False)
    with pytest.raises(l.selection.EngineUnavailable):run(l)
    assert l.calls==l.sdk_calls==[]
    with pytest.raises(l.selection.EngineUnavailable):
        l.sdk_service.prepare_reserved(None,l.sdk_service.PrepareRequest(job_id='job',run_id='run'))


@pytest.mark.parametrize('change',['content','key','part','total','share'])
def test_plan_part_cannot_be_rewritten(real_lane,change):
    m=real_lane.delivery
    content,plan=m.build_plan('hermes:reply:x','reply','Verified reply.','sms')
    meta={'delivery_group':{'key':'hermes:reply:x','part':1,'total':1},'sales_asset_share_ids':[]};key='hermes:reply:x'
    if change=='content':content+=' altered'
    if change=='key':key='hermes:reply:y'
    if change=='part':meta['delivery_group']['part']=2
    if change=='total':meta['delivery_group']['total']=2
    if change=='share':meta['sales_asset_share_ids']=['foreign']
    with pytest.raises(PermissionError):m.verify_plan_part(plan,meta,content,key)


def test_material_plan_hashes_no_token(real_lane):
    m=real_lane.delivery;token='opaque-test-only';url='https://example.invalid/api/v1/projects/a/'+token
    content,plan=m.build_plan('hermes:materials:r:o','material','Approved material:\n'+url,'sms',
        share_hashes={'s1':m.digest_text(token)},operation_id='op')
    assert token in content and token not in str(plan) and plan['parts'][0]['share_ids']==['s1']
    with pytest.raises(PermissionError):m.build_plan('hermes:materials:r:o','material','Approved material:\n'+url,'sms',share_hashes={'s2':'bad'})


def test_private_authentication_and_request_shape(real_lane,monkeypatch):
    from fastapi import HTTPException
    from pydantic import ValidationError
    service=real_lane.sdk_service
    monkeypatch.setenv('HERMES_INTERNAL_TOKEN','x'*32)
    service.authorize('Bearer '+'x'*32)
    with pytest.raises(HTTPException) as exc:service.authorize('Bearer wrong')
    assert exc.value.status_code==401
    with pytest.raises(ValidationError):service.PrepareRequest(job_id='job',run_id='run',prompt='injected')
    monkeypatch.delenv('HERMES_INTERNAL_TOKEN')
    with pytest.raises(HTTPException) as exc:service.authorize(None)
    assert exc.value.status_code==503


def test_real_material_issue_dispatch_and_receipt(real_lane,tmp_path,monkeypatch):
    """Use actual asset service, file integrity, outbox, and receipt; no provider network."""
    from hashlib import sha256
    from app.core.config import settings
    from app.modules.projects.models import (ProjectPropertyType,ProjectOnboardingSource,ProjectSourceKind,
        ProjectSourceStatus,ProjectSalesAsset,SalesAssetShare)
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    from app.modules.hermes_sales_core.bp_state_store import blank_state
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    l=real_lane;db=l.db
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path))
    monkeypatch.setattr(settings,'PUBLIC_APP_URL','https://example.invalid')
    db.add(ProjectPropertyType(id='type-a',project_id='project',name='Van Buren',review_status='confirmed',bedrooms=3))
    db.get(l.Message,'inbound').content='Please send me the brochure for Van Buren.'
    asset_ids=[]
    for i in range(2):
        payload=b'%PDF-1.4\n% Synthetic asset '+str(i).encode()+b'\n%%EOF'
        (tmp_path/f'{i}.pdf').write_bytes(payload)
        source=ProjectOnboardingSource(id=f'source-{i}',project_id='project',kind=ProjectSourceKind.UPLOADED_FILE,
            status=ProjectSourceStatus.READY,name=f'Brochure {i}',mime_type='application/pdf',storage_path=f'{i}.pdf',
            is_encrypted=False,content_hash=sha256(payload).hexdigest())
        db.add(source)
        asset=ProjectSalesAsset(id=f'asset-{i}',company_id='co',project_id='project',property_type_id='type-a',source_id=source.id,
            asset_type='brochure',content_tags=['brochure'],display_name=f'Brochure {i}',approval_status='approved',
            approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp'])
        db.add(asset);asset_ids.append(asset.id)
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        state=blank_state(l.scope);state['conversation_focus']['property_type_id']='type-a'
        state['offered_assets']={'pending_request':{'id':'request-material','source_inbound_message_id':'inbound',
            'unit_id':'type-a','subject':'brochure','asset_ids':asset_ids,
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}}
        run=reserve_live_run(db,l.scope,inbound_message_id='inbound')
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult(
            'I found the requested material. I still need to validate the share before sending it.',[],[
                {'tool':'get_unit_media','status':'executed','error_code':None}]),state),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare
    run(l)
    assert len(l.calls)==2 and '/projects/a/' in l.calls[1]
    shares=db.query(SalesAssetShare).all();assert len(shares)==2 and all(s.outbound_message_id for s in shares)
    op=db.query(HermesSalesOperation).one();assert op.status=='completed' and op.result_json['status']=='provider_accepted'
    assert all('/projects/a/' not in str(x) for x in [op.result_json,db.query(l.Run).one().output_snapshot])
    assert db.get(l.Job,'job').status=='processed' and l.load(db,l.scope).revision==2
    # Simulated crash after all receipts, before final inbound completion: no remint/re-send.
    db.get(l.Job,'job').status='processing';db.commit();run(l)
    assert len(l.calls)==2 and len(l.sdk_calls)==1 and db.query(SalesAssetShare).count()==2


def test_real_booking_effect_and_confirmation(real_lane):
    """Native appointment service and Calendar receipt, provider fake only."""
    from app.modules.projects.models import Project,ProjectPropertyType
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock,Meeting
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    from app.modules.hermes_sales_core.bp_state_store import blank_state,save
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from zoneinfo import ZoneInfo
    l=real_lane;db=l.db
    clock=datetime.now(timezone.utc);starts=(clock+timedelta(days=1)).replace(minute=0,second=0,microsecond=0)
    local=starts.astimezone(ZoneInfo('America/Lima'));date=local.date().isoformat();hour=local.strftime('%H:%M')
    db.get(Project,'project').address='123 Main Street'
    db.add_all([ProjectPropertyType(id='type-a',project_id='project',name='Van Buren',review_status='confirmed',
                available_units=1,inventory_updated_at=clock.replace(tzinfo=None)),
        User(id='advisor',company_id='co',first_name='Test',last_name='Advisor',email='advisor@example.invalid',
             hashed_password='not-a-real-password',role=UserRole.SALES,is_active=True),
        ProjectUserAssignment(id='assignment',project_id='project',user_id='advisor',responsibility='sales',
            sales_enabled=True,accepts_appointments=True,is_active=True),
        SalesAvailabilityBlock(id='slot',user_id='advisor',starts_at=starts.replace(tzinfo=None),
            ends_at=(starts+timedelta(hours=1)).replace(tzinfo=None),timezone='America/Lima')])
    inbound=db.get(l.Message,'inbound');inbound.content='Yes, I confirm the visit.'
    for i,(mid,text) in enumerate([('offer',f'Van Buren (type-a) has a visit time on {date} at {hour}.'),
         ('recap',f'Confirm Van Buren (type-a) on {date} at {hour} (America/Lima), 123 Main Street?')]):
        out=l.Out(id='out-'+mid,conversation_id='conversation',idempotency_key='historical:'+mid,channel='sms',provider='telnyx',
            content=text,status='sent',provider_message_id='provider-'+mid)
        row=l.Message(id=mid,conversation_id='conversation',direction='outbound',role='assistant',channel='sms',
            content=text,status='sent',provider_message_id='provider-'+mid,created_at=inbound.created_at-timedelta(seconds=3-i),
            metadata_json={'lead_id':'lead','project_id':'project','outbound_message_id':out.id})
        db.add_all([out,row])
    db.flush()
    slot={'date':date,'start_time':hour,'starts_at_utc':starts.isoformat()}
    expires=(clock+timedelta(minutes=10)).isoformat()
    state=blank_state(l.scope);state['conversation_focus']['property_type_id']='type-a'
    state['last_slot_search']={'proposal_id':'proposal','unit_id':'type-a','project_id':'project',
        'timezone':'America/Lima','options':[slot],'source_reply_message_id':'offer','expires_at':expires}
    state['confirmation_request']={'id':'request-book','kind':'book','status':'awaiting_confirmation','proposal_id':'proposal',
        'unit_id':'type-a',**slot,'timezone':'America/Lima','visit_address':'123 Main Street','recap_message_id':'recap',
        'selected_inbound_message_id':'earlier-inbound','expires_at':expires}
    save(db,l.scope,expected_revision=0,event_key='prior-recap',state=state);db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        draft=deepcopy(state);draft['confirmation_request']={**draft['confirmation_request'],
            'status':'execution_requested','confirmed_inbound_message_id':'inbound'}
        run=reserve_live_run(db,l.scope,inbound_message_id='inbound')
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',1,TurnResult(
            'I will check whether your selected visit can be confirmed. It is not booked yet.',[],[
                {'tool':'book_onsite_visit','status':'executed','error_code':None}]),draft),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare;run(l)
    assert len(l.calls)==2 and 'Your visit for Van Buren is confirmed' in l.calls[1]
    meeting=db.query(Meeting).one();booking=db.query(SalesBookingOperation).one()
    assert meeting.duration_minutes==60 and booking.meeting_id==meeting.id and booking.calendar_status=='pending'
    assert db.query(HermesSalesOperation).one().status=='completed'
    assert db.query(l.Run).one().output_snapshot['native_live_booking']['delivery']=='provider_accepted'
    db.get(l.Job,'job').status='processing';db.commit();run(l)
    assert db.query(Meeting).count()==1 and len(l.calls)==2 and len(l.sdk_calls)==1


def test_private_preparation_releases_database_before_sdk(real_lane,monkeypatch):
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    l=real_lane;db=l.db
    monkeypatch.setenv('OPENROUTER_API_KEY','fake-not-a-real-key')
    calls=[]
    def fake(self,request):
        assert not db.in_transaction()
        calls.append(request.message)
        return TurnResult('I can help with property details.',[],[])
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake)
    run=reserve_live_run(db,l.scope,inbound_message_id='inbound');rid=run.id;db.commit()
    request=l.sdk_service.PrepareRequest(job_id='job',run_id=rid)
    assert l.sdk_service.prepare_reserved(db,request)=={'run_id':rid,'status':'draft_ready'}
    assert l.sdk_service.prepare_reserved(db,request)=={'run_id':rid,'status':'draft_ready'}
    assert len(calls)==1 and db.query(l.Run).one().output_snapshot['live_draft']
