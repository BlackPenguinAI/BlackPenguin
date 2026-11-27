"""Real HTTP sockets, actual worker and ASGI app, no external model/providers."""
import asyncio
import os
import pytest
from test_bp_hei03b3_worker_delivery import real_lane  # noqa: F401
from sdk_scenarios import hei06_lane_engine, seed_catalog, first_input, state
from staging_transport import loopback_server, attach_http_worker, check_environment

pytestmark = pytest.mark.usefixtures('hei06_lane_engine')

@pytest.fixture
def http_lane(real_lane, monkeypatch, tmp_path):
    check_environment()
    seed_catalog(real_lane, monkeypatch, tmp_path)
    with loopback_server(real_lane.sdk_service.app) as origin:
        prepare = attach_http_worker(real_lane, monkeypatch, origin)
        yield real_lane, origin, prepare


def test_closed_gate_and_auth(http_lane, monkeypatch):
    import httpx
    lane, origin, _ = http_lane
    monkeypatch.setattr(lane.selection, 'live_hermes_ready', lambda:False)
    with httpx.Client(base_url=origin, trust_env=False) as client:
        good={'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']}
        body={'job_id':'job','run_id':'unreserved'}
        assert client.post('/internal/prepare', json=body).status_code==401
        assert client.post('/internal/prepare', json=body, headers={'Authorization':'Bearer invalid'}).status_code==401
        assert client.post('/internal/prepare', json={**body,'prompt':'not accepted'}, headers=good).status_code==422
        assert client.post('/internal/prepare', json=body, headers=good).status_code==503
        assert client.get('/openapi.json').status_code==404
    assert lane.db.query(lane.Run).count()==0 and not lane.calls


def test_unknown_job_and_invalid_run(http_lane):
    import httpx
    lane, origin, _ = http_lane
    good={'Authorization':'Bearer '+os.environ['HERMES_INTERNAL_TOKEN']}
    with httpx.Client(base_url=origin, trust_env=False) as client:
        assert client.post('/internal/prepare',json={'job_id':'unknown','run_id':'unknown'},headers=good).status_code==409
        assert client.post('/internal/prepare',json={'job_id':'job','run_id':'wrong-run'},headers=good).status_code==409
    assert lane.db.query(lane.Run).count()==0 and not lane.calls


def test_socket_worker_receipt_and_replay(http_lane, monkeypatch):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    lane, _, prepare = http_lane
    inference=[]
    def fake(runtime, request):
        inference.append(request.message)
        prop=request.verified_context['focused_property']
        assert prop['display_name']=='Van Buren' and prop['bedrooms']==3
        return TurnResult('Van Buren has 3 bedrooms.',[],[])
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake)
    first_input(lane,'Tell me the number of bedrooms in Van Buren.')
    assert state(lane)['conversation_focus']['property_type_id']=='van'
    assert lane.calls==['Van Buren has 3 bedrooms.'] and len(inference)==1
    lane.db.get(lane.Job,'job').status='processing';lane.db.commit()
    asyncio.run(lane.job.run_job(lane.db,'job',prepare=prepare))
    assert lane.db.get(lane.Job,'job').status=='processed'
    assert len(lane.calls)==len(inference)==len(lane.sdk_calls)==1


def test_socket_queued_receipt_no_duplicate(http_lane, monkeypatch):
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    lane, _, prepare = http_lane
    inference=[]
    def fake(runtime, request):
        inference.append(request.message)
        return TurnResult('I can help you explore the available homes.',[],[])
    monkeypatch.setattr(HermesSalesRuntime,'process_turn',fake)
    lane.status[0]='queued'
    with pytest.raises(lane.delivery.ReceiptPending):
        asyncio.run(lane.job.run_job(lane.db,'job',prepare=prepare))
    lane.job.mark_failure(lane.db,'job',pending=True)
    assert lane.load(lane.db,lane.scope).revision==0
    lane.db.query(lane.Out).one().status='sent'
    lane.db.query(lane.Message).filter_by(direction='outbound').one().status='sent'
    lane.db.get(lane.Job,'job').status='processing';lane.db.commit()
    asyncio.run(lane.job.run_job(lane.db,'job',prepare=prepare))
    assert lane.load(lane.db,lane.scope).revision==1
    assert len(lane.calls)==len(inference)==len(lane.sdk_calls)==1
