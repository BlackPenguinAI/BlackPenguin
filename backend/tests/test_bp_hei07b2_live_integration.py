"""Real ORM fixture regression; external SDK/provider calls remain simulated."""
from datetime import datetime, timezone
from copy import deepcopy

import pytest

from test_bp_hei03b3_worker_delivery import real_lane, run  # noqa: F401


def test_sdk_busy_retries_same_reserved_run_and_not_provider(real_lane):
    from app.modules.hermes_sales_core.live_job import SDKPreparationError, failure_evidence
    l=real_lane
    prepare=l.prepare
    async def busy(job_id,run_id):
        raise SDKPreparationError({'sdk_http_status':409,'sdk_error_code':'SDK_BUSY'})
    l.prepare=busy
    with pytest.raises(SDKPreparationError) as exc:
        run(l)
    rid=l.db.query(l.Run).one().id
    assert not l.calls and l.db.query(l.Out).count()==0
    l.job.mark_failure(l.db,'job',sdk_busy=True,diagnostic=failure_evidence(exc.value,'sdk_prepare'))
    assert l.db.get(l.Job,'job').status=='retry'
    assert l.db.get(l.Job,'job').error_code=='HERMES_SDK_BUSY'
    l.db.get(l.Job,'job').status='processing';l.db.commit()
    l.prepare=prepare
    run(l)
    assert l.db.query(l.Run).one().id==rid
    assert len(l.calls)==1 and l.db.get(l.Job,'job').status=='processed'


def test_busy_attempt_limit_leaves_review_without_delivery(real_lane):
    l=real_lane
    l.db.get(l.Job,'job').attempt_number=5;l.db.commit()
    l.job.mark_failure(l.db,'job',sdk_busy=True,diagnostic={'sdk_error_code':'SDK_BUSY'})
    assert l.db.get(l.Job,'job').status=='review'
    assert l.db.query(l.Out).count()==0 and not l.calls


def test_blueprints_discovers_brochure_but_never_shares_it(real_lane):
    from app.modules.projects.models import (ProjectPropertyType,ProjectOnboardingSource,ProjectSourceKind,
        ProjectSourceStatus,ProjectSalesAsset,SalesAssetShare)
    from app.modules.hermes_sales_core.bp_state_store import blank_state
    from app.modules.hermes_sales_core.bp_context import build_bp_snapshot
    from app.modules.hermes_sales_core.live_preparation import _live_port, reserve_live_run
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft
    from app.modules.hermes_sales_core.bp_p04_turn import P04PreparedTurn
    from app.modules.hermes_sales_core.bp_turn import PreparedHermesTurn
    from app.modules.hermes_sales_core.contracts import TurnResult
    l=real_lane;db=l.db
    db.add(ProjectPropertyType(id='type-a',project_id='project',name='Cleveland',review_status='confirmed',bedrooms=3));db.flush()
    inbound=db.get(l.Message,'inbound');inbound.content='Do you have blueprints for Cleveland?'
    db.add(ProjectOnboardingSource(id='source',project_id='project',kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY,name='Cleveland brochure',mime_type='application/pdf',storage_path='brochure.pdf',
        is_encrypted=False,content_hash='a'*64));db.flush()
    db.add(ProjectSalesAsset(id='asset',company_id='co',project_id='project',property_type_id='type-a',source_id='source',
        asset_type='brochure',content_tags=['brochure'],display_name='Cleveland brochure',approval_status='approved',
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp']))
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        snapshot=build_bp_snapshot(db,l.scope,channel='sms')
        state=blank_state(l.scope)
        port=_live_port(db,snapshot,state,db.get(l.Message,'inbound'),[]);port.prepare_context({})
        result=port.invoke('get_unit_media',{'unit_id':'type-a'},l.scope)
        assert result['ok'] and result['share_issued'] is False
        assert result['assets']==[] and set(result['assets_by_subject'])=={'brochure'}
        assert not state['offered_assets'].get('pending_request')
        reply='I have an approved brochure for Cleveland, but no separately verified floor plan.'
        reserved=reserve_live_run(db,l.scope,inbound_message_id='inbound');assert reserved.id==run_id
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult(reply,[],[
            {'tool':'get_unit_media','status':'executed','error_code':None}]),deepcopy(state)),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare
    run(l)
    assert len(l.calls)==1 and db.query(SalesAssetShare).count()==0
    assert db.get(l.Job,'job').status=='processed'
    assert l.load(db,l.scope).data['conversation_focus']['property_type_id']=='type-a'
