"""Single deployed topology and live scoped reads, with all model/network I/O mocked."""
import asyncio,json
from unittest.mock import patch
import pytest
from test_sales_booking_pilot import lab
from test_sales_observation_loop import prepared

@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_live_scoped_read_uses_loop_without_simulation_and_without_external_effects(lab,channel):
    from app.modules.sales_agent.observation_loop import run
    from app.modules.sales_agent.execution import simulated
    from app.modules.sales_crm.models import Meeting,Lead
    from app.modules.sales_agent.models import OutboundMessage
    from app.modules.projects.models import SalesAssetShare
    db,scope,conv,msg,out=prepared(lab,'Please show photos')
    conv.channel=msg.channel=channel;conv.provider='telnyx'
    lead=db.get(Lead,scope.lead_id);lead.consent_status='granted';lead.agent_status='active';db.commit()
    seen=[]
    async def infer(messages,schema):
        assert not simulated(scope)
        payload=json.loads(messages[1]['content']);seen.append(payload)
        keys=list(payload['available_tools'])
        return json.dumps({'action':'read' if keys else 'respond','tool_ids':keys[:4]})
    outcome,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer))
    assert seen and audit['status']=='PASS' and audit['tools']
    assert any(d.get('observed_operations') for d in audit['decisions'])
    assert db.query(Meeting).count()==db.query(OutboundMessage).count()==db.query(SalesAssetShare).count()==0


def test_permission_change_after_model_await_prevents_read(lab):
    from app.modules.sales_agent.observation_loop import run
    db,scope,conv,msg,out=prepared(lab,'Please show photos')
    checks=[]
    def authorize():
        checks.append(True)
        if len(checks)>1:raise PermissionError('Permission revoked during inference.')
    async def infer(messages,schema):
        keys=list(json.loads(messages[1]['content'])['available_tools'])
        return json.dumps({'action':'read','tool_ids':keys[:1]})
    outcome,audit=asyncio.run(run(db,scope,inbound=msg,outcome=out,commercial={},infer=infer,authorize=authorize))
    assert audit['status']=='FAIL' and not audit['tools'] and audit['external_writes']==0


def test_health_identifies_shared_engine_without_calling_model():
    from app.modules.health.router import sales_engine
    result=sales_engine()
    assert result['orchestrator']=='graph-observe' and result['engine']=='sales-langgraph/2.0'
    assert result['channels']==['sms','whatsapp','simulation'] and result['max_tool_rounds']==2

from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent

@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_actual_live_entry_runs_full_graph_and_retry_does_not_send_twice(agent,monkeypatch,channel):
    from app.modules.sales_agent import observation_loop
    from app.modules.sales_agent.execution import simulated
    from test_sales_active_integration import understanding
    from test_sales_ai_group_c import product
    product(agent,'Synthetic Home')
    agent.conversation.channel=channel;agent.db.commit()
    original=observation_loop.run
    seen=[]
    async def decision(messages,schema):
        assert not simulated(agent.scope)
        payload=json.loads(messages[1]['content']);seen.append(payload)
        keys=list(payload['available_tools'])[:4]
        return json.dumps({'action':'read' if keys else 'respond','tool_ids':keys})
    async def observed(*args,**kwargs):return await original(*args,**kwargs,infer=decision)
    monkeypatch.setattr(observation_loop,'run',observed)
    msg,run=agent.turn('Show me available properties',understanding('Show me available properties','catalog'))
    assert not run.error_code,run.output_snapshot
    assert seen and run.graph_version=='sales-langgraph/2.0'
    assert run.input_snapshot['coordinator_graph']['trace']==['interpret','plan','observe','fulfill']
    assert run.input_snapshot['coordinator_graph']['status']=='completed'
    assert run.input_snapshot['observation_loop']['status']=='PASS'
    assert run.output_snapshot['metadata']['orchestrator']=='graph-observe'
    sent=agent.send.await_count
    assert sent>0
    agent.retry(msg)
    assert agent.send.await_count==sent
    agent.legacy.assert_not_called()


def test_real_trace_export_is_read_only_and_keeps_historical_engine(agent,monkeypatch):
    from app.modules.sales_agent.models import AgentRun
    from tools.sales_ai import inspect_commercial_graph as inspect
    from app.db import postgres
    from sqlalchemy import event
    old=AgentRun(conversation_id=agent.conversation.id,event_id='historic-export',mode='live',
        graph_version='sales-active/1.0',toolset_version='historic',model='test/offline',
        prompt_snapshot={},input_snapshot={},output_snapshot={'reply':'Historical response'})
    agent.db.add(old);agent.db.commit()
    engine=agent.db.get_bind();statements=[]
    event.listen(engine,'before_cursor_execute',lambda conn,cursor,statement,*args:statements.append(statement))
    monkeypatch.setattr(postgres,'engine',engine)
    monkeypatch.setattr(inspect,'create_engine',lambda *args,**kwargs:engine)
    monkeypatch.setattr(engine,'dispose',lambda:None)
    report=inspect.export(agent.conversation.id)
    assert report['read_only'] and report['turns'][0]['graph_version']=='sales-active/1.0'
    assert report['turns'][0]['coordinator_graph'] is None
    assert report['deployed']['engine']=='sales-langgraph/2.0'
    assert all(s.lstrip().upper().startswith('SELECT') for s in statements)


def test_failed_live_decision_never_claims_missing_catalog_or_refers_to_sales_team(agent,monkeypatch):
    from app.modules.sales_agent import observation_loop
    from app.modules.sales_agent.models import OutboundMessage
    from app.modules.projects.models import SalesAssetShare
    from test_sales_active_integration import understanding
    real=observation_loop.run
    async def unavailable(*args):raise TimeoutError('mock decision provider unavailable')
    async def observed(*args,**kwargs):return await real(*args,**kwargs,infer=unavailable)
    monkeypatch.setattr(observation_loop,'run',observed)
    msg,run=agent.turn('Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    assert run.input_snapshot['coordinator_graph']['current_node']=='observe'
    assert run.input_snapshot['coordinator_graph']['status']=='failed'
    assert run.input_snapshot['observation_loop']['status']=='FAIL'
    reply=run.output_snapshot['reply'].lower()
    assert 'try again' in reply and 'sales team' not in reply and 'not available for this property' not in reply
    assert not agent.db.query(SalesAssetShare).count()
    assert run.output_snapshot.get('proposed_actions',[])==[]
