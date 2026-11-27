"""Paid real SDK scenarios, with actual private loopback HTTP and fake providers."""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog
from staging_transport import loopback_server, attach_http_worker, check_environment
from staging_scenarios import CASES, CASE_IDS, CHECKPOINTS, exercise
from diagnostics import SafeTrace, PROPERTY
from lifecycle_evidence import LifecycleEvidence, PROPERTY as LIFECYCLE_PROPERTY, state_shape, reply_shape

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')

@pytest.mark.parametrize('family,variant', CASES, ids=CASE_IDS)
def test_staging_scenario(real_lane, monkeypatch, tmp_path, record_property, family, variant):
    check_environment(model=True)
    seed_catalog(real_lane,monkeypatch,tmp_path)
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    trace=SafeTrace();original=HermesSalesRuntime.process_turn
    original_prepare=real_lane.sdk_service.prepare_reserved
    lifecycle=LifecycleEvidence()
    from app.modules.hermes_sales_core import live_preparation
    import staging_scenarios
    original_turn=live_preparation.prepare_live_turn
    original_state=staging_scenarios.state
    last_inbound=[None]
    last_port=[None]; domain_count=[0]
    def prepared(*args,**kwargs):
        turn=original_turn(*args,**kwargs)
        if last_port[0] is not None:
            lifecycle.tools('domain_tool',getattr(last_port[0],'domain_observations',[])[domain_count[0]:])
        lifecycle.add('prepared',**state_shape(turn.prepared.proposed_state,turn.prepared.inbound_message_id,menus=turn.proposed_menus),**reply_shape(turn.prepared.result.reply))
        return turn
    def persisted(lane):
        value=original_state(lane)
        lifecycle.add('persisted',**state_shape(value,last_inbound[0]))
        if lane.calls:lifecycle.add('outbound',**reply_shape(lane.calls[-1]))
        return value
    monkeypatch.setattr(live_preparation,'prepare_live_turn',prepared)
    monkeypatch.setattr(staging_scenarios,'state',persisted)
    def observed(runtime,request):
        trace.add('runtime_started')
        port=runtime._port
        last_inbound[0]=port.inbound_id
        last_port[0]=port;domain_count[0]=len(getattr(port,'domain_observations',[]))
        lifecycle.add('before_sdk',**state_shape(port.state,port.inbound_id),
            primary_captured=bool(port.primary_captured),prepared_visit=bool(getattr(port,'prepared_visit',None)),
            choice_type=(port.choice or {}).get('type') or 'none')
        lifecycle.tools('domain_tool',getattr(port,'domain_observations',[]))
        try:result=original(runtime,request)
        except Exception as exc:
            trace.error('runtime_error',exc);raise
        trace.add('runtime_returned');trace.tools(result.tool_observations);trace.reply(result.reply,'sdk')
        lifecycle.add('after_sdk',**state_shape(port.state,port.inbound_id),**reply_shape(result.reply))
        lifecycle.tools('sdk_tool',result.tool_observations)
        return result
    def prepare(db,request):
        trace.add('prepare_started')
        try:result=original_prepare(db,request)
        except Exception as exc:
            trace.error('prepare_error',exc);lifecycle.failure(exc);raise
        trace.add('prepare_returned');return result
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',observed)
    monkeypatch.setattr(real_lane.sdk_service,'prepare_reserved',prepare)
    def checkpoint(code):
        assert code in CHECKPOINTS
        record_property('staging_checkpoint',code)
    try:
        with loopback_server(real_lane.sdk_service.app) as origin:
            attach_http_worker(real_lane,monkeypatch,origin)
            exercise(real_lane,family,variant,checkpoint)
    except Exception as exc:
        lifecycle.failure(exc)
        raise
    finally:
        record_property(PROPERTY,trace.serialized())
        record_property(LIFECYCLE_PROPERTY,lifecycle.serialized())
