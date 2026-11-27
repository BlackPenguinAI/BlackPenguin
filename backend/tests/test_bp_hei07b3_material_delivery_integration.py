"""Real ORM/dispatcher contract with synthetic material; SDK/provider mocked."""
from datetime import datetime, timezone
from hashlib import sha256

from test_bp_hei03b3_worker_delivery import real_lane, run  # noqa: F401


def test_native_delivery_keeps_model_composition_and_exact_share(real_lane,tmp_path,monkeypatch):
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
    from app.modules.hermes_sales_core.material_continuity import MATERIALS, redact
    l=real_lane;db=l.db
    monkeypatch.setattr(settings,'PROJECT_UPLOAD_ROOT',str(tmp_path))
    monkeypatch.setattr(settings,'PUBLIC_APP_URL','https://example.invalid')
    db.add(ProjectPropertyType(id='type-a',project_id='project',name='Van Buren',review_status='confirmed',bedrooms=3));db.flush()
    db.get(l.Message,'inbound').content='Please send me the brochure for Van Buren.'
    payload=b'%PDF-1.4\n% Synthetic brochure\n%%EOF'
    (tmp_path/'brochure.pdf').write_bytes(payload)
    db.add(ProjectOnboardingSource(id='source',project_id='project',kind=ProjectSourceKind.UPLOADED_FILE,
        status=ProjectSourceStatus.READY,name='Van Buren brochure',mime_type='application/pdf',storage_path='brochure.pdf',
        is_encrypted=False,content_hash=sha256(payload).hexdigest()));db.flush()
    db.add(ProjectSalesAsset(id='asset',company_id='co',project_id='project',property_type_id='type-a',source_id='source',
        asset_type='brochure',content_tags=['brochure'],display_name='Van Buren brochure',approval_status='approved',
        approved_at=datetime.now(timezone.utc).replace(tzinfo=None),allowed_channels=['sms','whatsapp']))
    db.commit()
    async def prepare(job_id,run_id):
        l.sdk_calls.append(run_id)
        snapshot=build_bp_snapshot(db,l.scope,channel='sms');state=blank_state(l.scope)
        port=_live_port(db,snapshot,state,db.get(l.Message,'inbound'),[]);port.prepare_context({})
        result=port.invoke('get_unit_media',{'unit_id':'type-a'},l.scope)
        assert result['delivery']=='pending_backend_share' and MATERIALS in result['next_action']
        assert db.query(SalesAssetShare).count()==0
        pending=state['offered_assets']['pending_request']
        pending['commercial_copy']={'template':f"Here is the Van Buren brochure.\n\n{MATERIALS}\n\nWould you like more details about Van Buren?"}
        reserved=reserve_live_run(db,l.scope,inbound_message_id='inbound');assert reserved.id==run_id
        turn=P04PreparedTurn(PreparedHermesTurn(l.scope,'inbound',0,TurnResult(
            'I found a matching resource. Let me get it for you.',[],[
                {'tool':'get_unit_media','status':'executed','error_code':None}]),state),[])
        persist_live_draft(db,l.scope,inbound_message_id='inbound',run_id=run_id,turn=turn);db.commit()
    l.prepare=prepare;run(l)
    assert len(l.calls)==2 and len(l.sdk_calls)==1
    assert l.calls[1].startswith('Here is the Van Buren brochure.')
    assert l.calls[1].endswith('Would you like more details about Van Buren?')
    assert l.calls[1].count('/projects/a/')==1 and MATERIALS not in l.calls[1]
    assert '/projects/a/' not in redact(l.calls[1])
    assert db.query(SalesAssetShare).count()==1
    assert db.get(l.Job,'job').status=='processed'
    assert l.load(db,l.scope).data['conversation_focus']['property_type_id']=='type-a'
