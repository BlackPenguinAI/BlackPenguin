"""Test-only real TCP transport. Never imported by a production entrypoint."""
from contextlib import contextmanager
import asyncio
import os
import socket
import threading
import time


@contextmanager
def loopback_server(app):
    import uvicorn
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False,
                                            lifespan='off', proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
    thread.start()
    try:
        end = time.monotonic()+10
        while not server.started and thread.is_alive() and time.monotonic()<end:
            time.sleep(.02)
        assert server.started, 'Private loopback HTTP server failed to start'
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), 'Private loopback HTTP server failed to stop'


def attach_http_worker(lane, monkeypatch, origin):
    """Same client, auth, IDs, timeout and receipt check; only test URL changes."""
    import sdk_scenarios
    monkeypatch.setattr(lane.job, 'SDK_URL', origin+'/internal/prepare')
    async def prepare(job_id, run_id):
        assert not lane.db.in_transaction()
        lane.sdk_calls.append(run_id)
        await lane.job.request_sdk_draft(job_id, run_id)

    def run_claimed(current, job_id):
        assert current is lane
        asyncio.run(lane.job.run_job(lane.db, job_id, prepare=prepare))
        job = lane.db.get(lane.Job, job_id)
        assert job.status == 'processed'
        inbound = lane.db.get(lane.Message, job.message_id)
        assert (inbound.metadata_json or {}).get('agent_turn_status') == 'answered'
        lane.db.commit()
        return job.message_id

    monkeypatch.setattr(sdk_scenarios, 'run_claimed', run_claimed)
    return prepare


def check_environment(*, model=False):
    assert os.environ.get('ENVIRONMENT') == 'test'
    assert os.environ.get('DATABASE_URL') == 'sqlite://'
    if model:
        assert os.environ.get('HEI06_RUN_MODEL') == '1'
        assert os.environ.get('OPENROUTER_API_KEY') not in (None, '', 'test-only')
        from run_agent import AIAgent
        assert callable(AIAgent)
    else:
        assert os.environ.get('OPENROUTER_API_KEY') == 'test-only'
