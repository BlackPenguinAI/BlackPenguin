"""Native live changes, isolated real ORM + fake provider and SDK only."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
from test_bp_hei03b3_worker_delivery import real_lane, run


def setup_visit(l, kind):
    from app.modules.projects.models import Project,ProjectPropertyType
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock,Meeting,MeetingStatus
    from app.modules.hermes_sales_core.bp_state_store import blank_state,save
    from app.modules.hermes_sales_core.live_changes import active_visits,draft_change,change_recap
    db=l.db;clock=datetime.now(timezone.utc);zone=ZoneInfo('America/Lima')
    original=(clock+timedelta(days=1)).replace(minute=0,second=0,microsecond=0)
    replacement=original+timedelta(hours=2)
    local=replacement.astimezone(zone);date=local.date().isoformat();hour=local.strftime('%H:%M')
    db.get(Project,'project').address='123 Main Street'
    db.add_all([ProjectPropertyType(id='type-a',project_id='project',name='Van Buren',review_status='confirmed',available_units=1,inventory_updated_at=clock.replace(tzinfo=None)),
        User(id='advisor',company_id='co',first_name='Test',last_name='Advisor',email='advisor@example.invalid',hashed_password='fake',role=UserRole.SALES,is_active=True),
        ProjectUserAssignment(id='assignment',project_id='project',user_id='advisor',responsibility='sales',sales_enabled=True,accepts_appointments=True,is_active=True),
        SalesAvailabilityBlock(id='slot',user_id='advisor',starts_at=replacement.replace(tzinfo=None),ends_at=(replacement+timedelta(hours=1)).replace(tzinfo=None),timezone='America/Lima')])
    db.add(Meeting(id='original',project_id='project',lead_id='lead',assigned_sales_user_id='advisor',meeting_time=original.replace(tzinfo=None),duration_minutes=60,
        modality='showroom',status=MeetingStatus.CONFIRMED,confirmation_status='confirmed',is_demo=False,visit_property_type_id='type-a',visit_address='123 Main Street',visit_location_label='Visit location',
        visit_context={'project_id':'project','project_name':'Test Homes','property_type_id':'type-a','property_type_name':'Van Buren','unit_id':None,'unit_code':None,'timezone':'America/Lima'}))
    db.flush()
    inbound=db.get(l.Message,'inbound');inbound.content='Yes, I confirm.'
    state=blank_state(l.scope);state['conversation_focus']['property_type_id']='type-a'
    source_text='Please cancel my visit.' if kind=='cancel' else f'Please reschedule my visit to {date} at {hour}.'
    selection=l.Message(id='selection',conversation_id='conversation',channel='sms',direction='inbound',role='user',content=source_text,status='received',provider_message_id='provider-selection',
        created_at=inbound.created_at-timedelta(seconds=4),metadata_json={'lead_id':'lead','project_id':'project'})
    db.add(selection)
    slot={'date':date,'start_time':hour,'starts_at_utc':replacement.isoformat()}
    expires=(clock+timedelta(minutes=9)).isoformat()
    def accepted(mid,text,seconds):
        out=l.Out(id='out-'+mid,conversation_id='conversation',idempotency_key='historical:'+mid,channel='sms',provider='telnyx',content=text,status='sent',provider_message_id='provider-'+mid)
        row=l.Message(id=mid,conversation_id='conversation',direction='outbound',role='assistant',channel='sms',content=text,status='sent',provider_message_id='provider-'+mid,
            created_at=inbound.created_at-timedelta(seconds=seconds),metadata_json={'lead_id':'lead','project_id':'project','outbound_message_id':out.id})
        db.add_all([out,row]);return row
    if kind=='reschedule':
        accepted('offer',f'Van Buren (type-a) is available on {date} at {hour}.',6)
        state['last_slot_search']={'proposal_id':'proposal','unit_id':'type-a','project_id':'project','timezone':'America/Lima','options':[slot],'source_reply_message_id':'offer','expires_at':expires}
    db.flush()
    port=SimpleNamespace(db=db,snapshot=SimpleNamespace(scope=l.scope),now=clock,state=state,message=source_text,inbound_id='selection')
    args={'meeting_id':'original'} if kind=='cancel' else {'original_meeting_id':'original','unit_id':'type-a','proposal_id':'proposal','date_str':date,'start_time':hour}
    outcome=draft_change(port,kind,args)
    assert outcome.get('ok'),outcome
    request=deepcopy(state['confirmation_request']);recap=accepted('recap',change_recap(request),2)
    request.update(status='awaiting_confirmation',recap_message_id=recap.id)
    state['confirmation_request']=request
    db.flush();save(db,l.scope,expected_revision=0,event_key='prior-recap',state=state);db.commit()
    def install():
        from app.modules.hermes_sales_core.live_preparation import reserve_live_run
        from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
        from app.modules.hermes_sales_core.contracts import TurnResult
        from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
        from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
        async def prepare(job_id,run_id):
            l.sdk_calls.append(run_id)
            draft=deepcopy(state)
            p=SimpleNamespace(db=db,snapshot=SimpleNamespace(scope=l.scope),now=datetime.now(timezone.utc),state=draft,message=db.get(l.Message,'inbound').content,inbound_id='inbound')
            outcome=draft_change(p,kind,args)
            assert outcome.get('ok'),outcome
            r=reserve_live_run(db,l.scope,inbound_message_id='inbound')
            turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',1,TurnResult('I will check your requested visit change.',[],[{'tool':kind=='cancel' and 'cancel_onsite_visit' or 'reschedule_onsite_visit','status':'executed','error_code':None}]),draft),[])
            persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
        l.prepare=prepare
    install()
    return SimpleNamespace(state=state,request=request,port=port,args=args,original=original,replacement=replacement)


@pytest.mark.parametrize('kind',['cancel','reschedule'])
def test_native_change_end_to_end_and_retry(real_lane,kind):
    from app.modules.sales_crm.models import Meeting,MeetingStatus
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    from app.modules.sales_agent.cancellation_models import SalesCancellationOperation
    from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    l=real_lane;fixture=setup_visit(l,kind);run(l)
    op=l.db.query(HermesSalesOperation).one()
    assert op.operation_type==kind and op.status=='completed'
    old=l.db.get(Meeting,'original');assert old.status==MeetingStatus.CANCELLED
    assert len(l.calls)==2 and len(l.sdk_calls)==1 and l.db.get(l.Job,'job').status=='processed'
    if kind=='cancel':
        native=l.db.query(SalesCancellationOperation).one();assert native.meeting_id==old.id
        assert native.notification_outbox_id and l.db.query(Meeting).count()==1 and 'cancelled' in l.calls[-1]
    else:
        native=l.db.query(SalesRescheduleOperation).one();new=l.db.get(Meeting,native.replacement_meeting_id)
        assert new.meeting_time==fixture.replacement.replace(tzinfo=None) and new.status in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED}
        assert l.db.query(SalesBookingOperation).count()==1 and 'rescheduled' in l.calls[-1]
    assert l.db.query(l.Run).one().output_snapshot['native_live_change']['delivery']=='provider_accepted'
    l.db.get(l.Job,'job').status='processing';l.db.commit();run(l)
    assert len(l.calls)==2 and len(l.sdk_calls)==1 and l.db.query(HermesSalesOperation).count()==1


def test_reschedule_unavailable_preserves_original(real_lane):
    from app.modules.sales_crm.models import Meeting,MeetingStatus,SalesAvailabilityBlock
    from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
    l=real_lane;setup_visit(l,'reschedule');l.db.query(SalesAvailabilityBlock).delete();l.db.commit()
    with pytest.raises(PermissionError,match='unavailable'):run(l)
    l.db.rollback();assert l.db.get(Meeting,'original').status==MeetingStatus.CONFIRMED
    assert l.db.query(Meeting).count()==1 and l.db.query(HermesSalesOperation).count()==0 and len(l.calls)==1


@pytest.mark.parametrize('message',['Do not cancel my visit.','Can you cancel my visit?','My friend said cancel my visit.','Cancel my visit or change the time.'])
def test_cancel_draft_rejects_ambiguous_or_negated(real_lane,message):
    from app.modules.hermes_sales_core.live_changes import draft_change
    l=real_lane;f=setup_visit(l,'cancel');f.port.state['confirmation_request']=None;f.port.message=message
    assert not draft_change(f.port,'cancel',f.args).get('ok')


@pytest.mark.parametrize('message',['Reschedule my visit to 2026-12-01 at 10:00 or 11:00.','Reschedule my visit to 2026-12-01 at 10:00, not 11:00.','Reschedule my visit to tomorrow.'])
def test_replacement_rejects_ambiguous_time(message):
    from app.modules.hermes_sales_core.live_changes import direct_replacement
    assert not direct_replacement(message)


def test_changed_original_rejects_before_inference_receipt(real_lane):
    from app.modules.sales_crm.models import Meeting
    l=real_lane;setup_visit(l,'cancel');l.db.get(Meeting,'original').duration_minutes=45;l.db.commit()
    with pytest.raises(AssertionError):run(l)
    assert not l.calls


def test_altered_recap_never_authorizes(real_lane):
    from app.modules.sales_crm.models import Meeting,MeetingStatus
    l=real_lane;setup_visit(l,'cancel');recap=l.db.get(l.Message,'recap');recap.content+=' Changed.';l.db.get(l.Out,'out-recap').content=recap.content;l.db.commit()
    # ORM state validation catches the changed recap before a reply is sent.
    with pytest.raises(PermissionError):run(l)
    l.db.rollback();assert l.db.get(Meeting,'original').status==MeetingStatus.CONFIRMED


def test_real_multi_subject_material_batch(real_lane,tmp_path,monkeypatch):
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
    db.get(l.Message,'inbound').content='Please send me the brochure and floor plan for Van Buren.'
    asset_ids=[]
    for i in range(2):
        payload=b'%PDF-1.4\n% Synthetic asset '+str(i).encode()+b'\n%%EOF'
        (tmp_path/f'{i}.pdf').write_bytes(payload)
        source=ProjectOnboardingSource(id=f'source-{i}',project_id='project',kind=ProjectSourceKind.UPLOADED_FILE,
            status=ProjectSourceStatus.READY,name=f'Brochure {i}',mime_type='application/pdf',storage_path=f'{i}.pdf',
            is_encrypted=False,content_hash=sha256(payload).hexdigest())
        db.add(source)
        asset=ProjectSalesAsset(id=f'asset-{i}',company_id='co',project_id='project',property_type_id='type-a',source_id=source.id,
            asset_type=['brochure','floor_plan'][i],content_tags=[['brochure','floor_plan'][i]],display_name=f'Document {i}',approval_status='approved',
            approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp'])
        db.add(asset);asset_ids.append(asset.id)
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        state=blank_state(l.scope);state['conversation_focus']['property_type_id']='type-a'
        state['offered_assets']={'pending_request':{'id':'request-material','source_inbound_message_id':'inbound',
            'unit_id':'type-a','subjects':['floor_plan','brochure'],'asset_ids':asset_ids,'asset_subjects':{asset_ids[0]:['brochure'],asset_ids[1]:['floor_plan']},
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


@pytest.mark.parametrize('text',['Please send me the brochure and floor plan.','Could you share the floor plan and photos?'])
def test_multi_subject_explicit_request(text):
    from app.modules.hermes_sales_core.live_multi_material import explicit_multi_subjects
    assert len(explicit_multi_subjects(text))==2

@pytest.mark.parametrize('text',['Please send me the brochure or floor plan.','Please send me the brochure, not the floor plan.','Do you have brochures and photos?','My friend said send me the brochure and floor plan.'])
def test_multi_subject_ambiguity_rejected(text):
    from app.modules.hermes_sales_core.live_multi_material import explicit_multi_subjects
    assert explicit_multi_subjects(text)==[]


def test_multi_subject_uncovered_rejected():
    from app.modules.hermes_sales_core.live_multi_material import subject_mapping
    with pytest.raises(PermissionError):
        subject_mapping({'asset_ids':['a'],'subjects':['brochure','floor_plan'],'asset_subjects':{'a':['brochure']}})


def test_multi_subject_draft_deduplicates_asset():
    from app.modules.hermes_sales_core.live_multi_material import draft_multi_material,subject_mapping
    a={'asset_id':'a','name':'Combined document','asset_type':'brochure'}
    port=SimpleNamespace(message='Please send me the brochure and floor plan.',state={},inbound_id='m',now=datetime.now(timezone.utc),
        _details=lambda args:{'ok':True,'property':{'reference':'p'}},_verified_assets=lambda row:{'brochure':[a],'floor_plan':[a]})
    result=draft_multi_material(port,{})
    assert result['ok'] and len(result['assets'])==1
    draft=port.state['offered_assets']['pending_request']
    assert subject_mapping(draft)=={'a':['floor_plan','brochure']}
