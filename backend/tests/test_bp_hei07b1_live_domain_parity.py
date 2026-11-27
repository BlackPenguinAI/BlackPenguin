"""Regression for Cedar's real conversation. No network, real leads or Calendar."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.hermes_sales_core.live_domain_parity import contextual_bedrooms
from test_bp_hei03b3_worker_delivery import real_lane, run  # noqa: F401


@pytest.mark.parametrize('message', ["I’m looking for a 2-bedroom house", "I'm looking for a 2-bedroom house", 'I am looking for a 2 bedroom home'])
def test_initial_buyer_declaration(message):
    assert contextual_bedrooms(message, {}) == {'bedrooms': {'mode':'preferred','preferred':2}}


@pytest.mark.parametrize('message', ["Yes, 3 bedrooms it’s ok", "Yes, 3 bedrooms it's ok", '3 bedrooms are fine'])
def test_explicit_acceptance_of_visible_alternative(message):
    prior={'active_search':{'criteria':{'bedrooms':2},'match_count':0}, 'search_preferences':{'bedrooms':{'mode':'preferred','preferred':2}}}
    reply='There are no matching homes. Would you like to explore 3-bedroom houses instead?'
    assert contextual_bedrooms(message, prior, reply) == {'bedrooms': {'mode':'preferred','preferred':3}}
    assert not contextual_bedrooms(message, prior, None)
    assert not contextual_bedrooms(message, prior, 'Would you like to explore 4-bedroom houses?')
    assert not contextual_bedrooms(message, {**prior,'active_search':{'match_count':1}}, reply)


@pytest.mark.parametrize('message', ['Show me other 3-bedroom houses', 'Would 3 bedrooms be ok?', 'Not 3 bedrooms', '3 bedrooms or 4 bedrooms', 'Yes', 'I am looking for a 3-bedroom house if possible'])
def test_no_permanent_preference_from_ambiguous_or_temporary_request(message):
    assert not contextual_bedrooms(message, {'active_search':{'match_count':0}}, 'Would you like to explore 3 bedrooms?')


def test_existing_primary_is_not_replaced_by_new_search():
    assert not contextual_bedrooms('I am looking for a 3-bedroom house', {'search_preferences':{'bedrooms':{'mode':'preferred','preferred':2}}})


def test_late_provider_receipt_after_new_inbound_preserves_previous_state(real_lane):
    from app.modules.sales_agent.engine_router import event_scope
    l=real_lane; l.status[0]='queued'
    with pytest.raises(l.delivery.ReceiptPending):
        run(l)
    l.job.mark_failure(l.db,'job',pending=True)
    assert l.load(l.db,l.scope).revision==0
    conv=l.db.get(l.Conversation,'conversation')
    row=l.db.query(l.Message).filter_by(direction='outbound').one()
    out=l.db.query(l.Out).one()
    # Authentic later inbound has arrived before the prior receipt poll.
    pin={**event_scope(conv,'telnyx:provider-next'),'engine':'hermes','policy_version_id':'version'}
    nxt=l.Message(id='next-inbound',conversation_id=conv.id,channel='sms',direction='inbound',role='user',
        content='Tell me more.',status='received',provider_message_id='provider-next',created_at=row.created_at+timedelta(seconds=1),
        metadata_json={'lead_id':'lead','project_id':'project','continuity_recorded':True,'sales_engine_pin':pin})
    l.db.add(nxt);l.db.flush()
    conv.continuity_json={**conv.continuity_json,'last_inbound_message_id':nxt.id,'waiting_for_lead':False}
    out.status=row.status='delivered'
    l.db.get(l.Job,'job').status='processing';l.db.commit()
    run(l)
    assert l.load(l.db,l.scope).revision==1
    assert l.db.query(l.Run).one().status=='completed'
    assert l.db.get(l.Job,'job').status=='processed'
    assert len(l.calls)==len(l.sdk_calls)==1
    assert l.db.get(l.Conversation,conv.id).continuity_json['last_inbound_message_id']==nxt.id


def test_receipt_only_cannot_create_execution(real_lane):
    from app.modules.hermes_sales_core.live_preparation import reserve_live_run
    from app.modules.hermes_sales_core.production_tools import ProductionToolError
    l=real_lane
    with pytest.raises(ProductionToolError):
        reserve_live_run(l.db,l.scope,inbound_message_id='inbound',receipt_only=True)
    assert l.db.query(l.Run).count()==0


def test_approved_material_discovery_without_sdk_storage(real_lane,tmp_path,monkeypatch):
    from hashlib import sha256
    from app.core.config import settings
    from app.modules.projects.models import (ProjectPropertyType,ProjectOnboardingSource,ProjectSourceKind,
        ProjectSourceStatus,ProjectSalesAsset,SalesAssetShare)
    from app.modules.hermes_sales_core.bp_state_store import blank_state
    from app.modules.hermes_sales_core.bp_context import build_bp_snapshot
    from app.modules.hermes_sales_core.live_preparation import _live_port, reserve_live_run
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.contracts import TurnResult
    from app.modules.hermes_sales_core.production_tools import _material_batch
    from app.modules.projects.models import Project
    l=real_lane;db=l.db
    sdk_root=tmp_path/'sdk';sdk_root.mkdir()
    api_root=tmp_path/'api';api_root.mkdir()
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(sdk_root))
    monkeypatch.setattr(settings,'PUBLIC_APP_URL','https://example.invalid')
    db.add(ProjectPropertyType(id='type-a',project_id='project',name='Cleveland',review_status='confirmed',bedrooms=3));db.flush()
    inbound=db.get(l.Message,'inbound');inbound.content='Please send me the brochure for Cleveland.'
    payload=b'%PDF-1.4\n% Synthetic brochure\n%%EOF'
    (api_root/'brochure.pdf').write_bytes(payload)
    source=ProjectOnboardingSource(id='source',project_id='project',kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY,name='Cleveland brochure',mime_type='application/pdf',storage_path='brochure.pdf',
        is_encrypted=False,content_hash=sha256(payload).hexdigest())
    db.add(source);db.flush()
    db.add(ProjectSalesAsset(id='asset',company_id='co',project_id='project',property_type_id='type-a',source_id=source.id,
        asset_type='brochure',content_tags=['brochure'],display_name='Cleveland brochure',approval_status='approved',
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp']))
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        snapshot=build_bp_snapshot(db,l.scope,channel='sms')
        state=blank_state(l.scope)
        port=_live_port(db,snapshot,state,db.get(l.Message,'inbound'),[])
        port.prepare_context({})
        result=port.invoke('get_unit_media',{'unit_id':'type-a'},l.scope)
        assert result['delivery']=='pending_backend_share' and result['share_issued'] is False
        assert result['assets'][0]['asset_id']=='asset'
        assert not (sdk_root/'brochure.pdf').exists()
        assert db.query(SalesAssetShare).count()==0
        # Physical verification stays mandatory in native backend, not in SDK.
        pending=state['offered_assets']['pending_request']
        with pytest.raises((ValueError,OSError,PermissionError)):
            _material_batch(db,l.scope,db.get(Project,'project'),'sms',pending,datetime.now(timezone.utc))
        db.rollback()
        monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(api_root))
        reserved=reserve_live_run(db,l.scope,inbound_message_id='inbound');assert reserved.id==run_id
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult(
            'I found the requested material. I still need to validate the share before sending it.',[],[
                {'tool':'get_unit_media','status':'executed','error_code':None}]),state),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare
    run(l)
    assert len(l.calls)==2 and '/projects/a/' in l.calls[1]
    assert db.query(SalesAssetShare).count()==1
    assert db.get(l.Job,'job').status=='processed'


def test_failure_evidence_does_not_copy_secrets():
    from app.modules.hermes_sales_core.live_job import failure_evidence
    try:
        raise ValueError('secret or private link')
    except ValueError as exc:
        info=failure_evidence(exc,'reply_state_commit')
    assert info['checkpoint']=='reply_state_commit' and info['exception_type']=='ValueError'
    assert 'secret' not in str(info).replace('test_failure_evidence_does_not_copy_secrets','')
    assert info['locations']
