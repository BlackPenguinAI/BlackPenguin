"""Regression coverage for retry evidence and strict opportunity attribution."""
from datetime import datetime, timedelta
import json
import pytest
from test_staff_monitor import monitor
from app.modules.sales_agent.models import SalesMessage, AgentRun, OutboundMessage, SalesConversationLeadContext


def test_long_history_pages_and_export_are_complete(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    for n in range(405):
        db.add(SalesMessage(conversation_id=conv.id,channel='sms',direction='inbound',role='user',content=f'Row {n}',metadata_json={'lead_id':lead.id},created_at=datetime(2026,2,1)+timedelta(seconds=n)))
    db.commit()
    ids=[];cursor=''
    for _ in range(10):
        page=client.get(f'/monitor/conversations/{conv.id}?{scope}&limit=100'+('&after='+cursor if cursor else '')).json()
        ids.extend(m['id'] for m in page['messages']);cursor=page['next_cursor']
        if not page['has_more']:break
    export=client.get(f'/monitor/conversations/{conv.id}/export?{scope}').json()
    assert len(ids)==len(set(ids))==407
    assert ids==[m['id'] for m in export['messages']]


def test_explicit_other_opportunity_runs_are_excluded_without_context_rows(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    db.add(AgentRun(conversation_id=conv.id,event_id='other-opportunity-explicit',mode='live',status='completed',graph_version='test',toolset_version='test',model='test/model',prompt_snapshot={'system':'OTHER_OPPORTUNITY_SECRET'},input_snapshot={'turn_trace':{'lead_id':second.id}},output_snapshot={}))
    db.commit()
    export=client.get(f'/monitor/conversations/{conv.id}/export?{scope}')
    assert export.status_code==200
    assert 'OTHER_OPPORTUNITY_SECRET' not in export.text


def test_context_history_excludes_other_runs_and_deliveries(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    db.add_all([SalesConversationLeadContext(conversation_id=conv.id,lead_id=lead.id,is_active=False),SalesConversationLeadContext(conversation_id=conv.id,lead_id=second.id,is_active=True)])
    conv.lead_id=second.id
    other_run=AgentRun(conversation_id=conv.id,event_id='other-context',mode='live',status='completed',graph_version='test',toolset_version='test',model='test/model',prompt_snapshot={'system':'OTHER_CONTEXT_SECRET'},input_snapshot={'turn_trace':{'lead_id':second.id}},output_snapshot={})
    db.add(other_run);db.flush()
    db.add(OutboundMessage(conversation_id=conv.id,agent_run_id=other_run.id,idempotency_key='other-context-delivery',channel='sms',provider='telnyx',content='OTHER_DELIVERY_SECRET',status='failed'))
    db.commit()
    export=client.get(f'/monitor/conversations/{conv.id}/export?{scope}')
    assert export.status_code==200
    assert 'OTHER_CONTEXT_SECRET' not in export.text
    assert 'OTHER_DELIVERY_SECRET' not in export.text


def test_monitor_reads_never_mutate_message_and_run_evidence(monitor):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    before=(inbound.content,outbound.content,json.dumps(run.input_snapshot,sort_keys=True),json.dumps(run.prompt_snapshot,sort_keys=True))
    for suffix in ('','/export'):
        assert client.get(f'/monitor/conversations/{conv.id}{suffix}?{scope}').status_code==200
    db.expire_all()
    after=(inbound.content,outbound.content,json.dumps(run.input_snapshot,sort_keys=True),json.dumps(run.prompt_snapshot,sort_keys=True))
    assert before==after


def test_retry_keeps_previous_actual_model_request(monitor):
    from app.modules.sales_agent.live_service import _prepare_run
    from app.modules.sales_agent.turn_trace import capture_model_request
    db,client,_,company,project,foreign,lead,second,conv,inbound,*_=monitor
    run=_prepare_run(db,conversation=conv,event_id='retry-model-request',message_id=inbound.id)
    request=[{'role':'user','content':'UNIQUE_FIRST_ATTEMPT_HISTORY'}]
    capture_model_request(db,{'event_id':run.event_id,'conversation_id':conv.id,'model':'test/model','prompt_snapshot':{'system':'First applied prompt'},'commercial_context':{}},request)
    run.status='failed';run.error_code='ProviderError';db.commit()
    retry=_prepare_run(db,conversation=conv,event_id=run.event_id,message_id=inbound.id)
    assert 'UNIQUE_FIRST_ATTEMPT_HISTORY' in json.dumps(retry.input_snapshot)


@pytest.mark.parametrize('source',['top_level','trace','prior_attempt','legacy_attempt','inbound_reference','outbound_reference'])
@pytest.mark.parametrize('conflicting_link',[False,True])
def test_explicit_attribution_overrides_legacy_and_conflicting_links(monitor,source,conflicting_link):
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    marker='DO_NOT_EXPORT_OTHER_EXECUTION'
    wrong=AgentRun(conversation_id=conv.id,event_id='wrong-owner',mode='live',status='completed',graph_version='test',toolset_version='test',model='test/model',prompt_snapshot={'system':marker},input_snapshot={},output_snapshot={})
    db.add(wrong);db.flush()
    if source=='top_level': snapshot={'lead_id':second.id}
    elif source=='trace': snapshot={'turn_trace':{'lead_id':second.id}}
    elif source=='prior_attempt': snapshot={'turn_trace':{'lead_id':lead.id},'trace_attempts':[{'input_snapshot':{'turn_trace':{'lead_id':second.id}}}]}
    elif source=='legacy_attempt': snapshot={'trace_attempts':[{'historical_input':{'lead_id':second.id}}]}
    else:
        message=SalesMessage(conversation_id=conv.id,channel='sms',direction='inbound' if source=='inbound_reference' else 'outbound',role='user' if source=='inbound_reference' else 'assistant',content='Other opportunity message',metadata_json={'lead_id':second.id,**({'agent_run_id':wrong.id} if source=='outbound_reference' else {})})
        db.add(message);db.flush()
        snapshot={'message_id':message.id} if source=='inbound_reference' else {}
    wrong.input_snapshot=snapshot
    if conflicting_link:
        outbound.metadata_json={**outbound.metadata_json,'agent_run_id':wrong.id}
    db.commit()
    response=client.get(f'/monitor/conversations/{conv.id}/export?{scope}')
    assert response.status_code==200
    assert marker not in response.text
    assert any('explicit attribution excluded' in text for text in response.json()['missing_evidence'])
    assert db.get(AgentRun,wrong.id).prompt_snapshot['system']==marker


def test_unattributed_legacy_run_is_still_available_with_missing_evidence(monitor):
    _,client,_,company,project,foreign,lead,second,conv,inbound,outbound,run,scope,_=monitor
    response=client.get(f'/monitor/conversations/{conv.id}/export?{scope}').json()
    assert [r['id'] for r in response['runs']]==[run.id]
    assert response['runs'][0]['missing_evidence']


def test_repeated_retries_preserve_full_inputs_in_a_flat_history(monitor):
    from app.modules.sales_agent.live_service import _prepare_run
    from app.modules.sales_agent.turn_trace import capture_model_request
    db,client,_,company,project,foreign,lead,second,conv,inbound,outbound,original_run,scope,_=monitor
    for n in range(4):
        run=_prepare_run(db,conversation=conv,event_id='repeated-retry',message_id=inbound.id)
        capture_model_request(db,{'event_id':run.event_id,'conversation_id':conv.id,'model':f'test/model-{n}','prompt_snapshot':{'system':f'Prompt {n}'},'commercial_context':{'approved_revision':n}},[{'role':'user','content':f'EXACT_REQUEST_{n}'}])
        run.status='failed';run.error_code=f'Error{n}';run.output_snapshot={'reply':f'Output {n}'};db.commit()
    run=_prepare_run(db,conversation=conv,event_id='repeated-retry',message_id=inbound.id)
    attempts=run.input_snapshot['trace_attempts']
    assert len(attempts)==5
    for n,attempt in enumerate(attempts[:-1]):
        assert attempt['input_snapshot']['model_request']['messages'][0]['content']==f'EXACT_REQUEST_{n}'
        assert 'trace_attempts' not in attempt['input_snapshot']
        assert attempt['input_snapshot']['graph_commercial_context']['approved_revision']==n
        assert attempt['model']==f'test/model-{n}'
        assert attempt['prompt_snapshot']['system']==f'Prompt {n}'
        assert attempt['output_snapshot']['reply']==f'Output {n}'
        assert attempt['error_code']==f'Error{n}'
    exported=client.get(f'/monitor/conversations/{conv.id}/export?{scope}').json()
    saved=next(r for r in exported['runs'] if r['id']==run.id)
    assert saved['input_snapshot']['trace_attempts']==attempts
