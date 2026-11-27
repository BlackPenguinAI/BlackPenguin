"""Paid real SDK scenarios, with actual private loopback HTTP and fake providers."""
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog
from staging_transport import loopback_server, attach_http_worker, check_environment
from staging_scenarios import CASES, CASE_IDS, CHECKPOINTS, exercise
from diagnostics import SafeTrace, PROPERTY

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')

@pytest.mark.parametrize('family,variant', CASES, ids=CASE_IDS)
def test_staging_scenario(real_lane, monkeypatch, tmp_path, record_property, family, variant):
    check_environment(model=True)
    seed_catalog(real_lane,monkeypatch,tmp_path)
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    trace=SafeTrace();original=HermesSalesRuntime.process_turn
    original_prepare=real_lane.sdk_service.prepare_reserved
    def observed(runtime,request):
        trace.add('runtime_started')
        try:result=original(runtime,request)
        except Exception as exc:
            trace.error('runtime_error',exc);raise
        trace.add('runtime_returned');trace.tools(result.tool_observations);trace.reply(result.reply,'sdk')
        return result
    def prepare(db,request):
        trace.add('prepare_started')
        try:result=original_prepare(db,request)
        except Exception as exc:
            trace.error('prepare_error',exc);raise
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
    finally:
        record_property(PROPERTY,trace.serialized())
