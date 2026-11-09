"""Connected acceptance probes and bounded real-model evaluation tooling.

This suite is fully offline. Probe tests use httpx.MockTransport; they do not
prove model quality or real PostgreSQL concurrency.
"""
import asyncio,json,os,subprocess,sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product
from test_sales_ai_group_d import typed,req,ref
from test_sales_ai_group_f import latest
from test_sales_ai_group_g import change
from test_sales_ai_group_h import cancellation,manager
from test_sales_ai_group_i import registered,add_block,worker
from test_sales_active_integration import understanding
from app.modules.sales_agent.dialogue_store import load
from app.modules.sales_agent.models import SalesMessage
from app.modules.sales_agent.wait_models import SalesWaitRequest
from app.modules.sales_agent.booking_models import SalesBookingOperation
from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
from app.modules.sales_agent.cancellation_models import SalesCancellationOperation
from app.modules.sales_agent.operational_context import snapshot
from app.modules.sales_crm.models import Meeting,MeetingStatus
from tools.sales_ai.evaluate_model import Budget,EvaluationBudgetExceeded,load_pack,scenarios,main,run_case,summarize
from tools.sales_ai.model_probe import probe,payload,MODEL,MAX_BYTES


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_wait_booking_enquiry_replacement_cancellation_connected_without_changing_consent(agent,channel):
    agent.conversation.channel=channel
    wait,starts=registered(agent);add_block(agent,starts);worker(agent)
    assert wait.status=='notified' and not agent.db.query(Meeting).count()
    agent.turn('1',typed('1',[req('pick','appointment','1',ref='s')],[ref('s','appointment','1')]))
    inbound,_=agent.turn('Yes',understanding('Yes','other'));original=agent.db.query(Meeting).one();agent.retry(inbound)
    assert agent.db.query(SalesBookingOperation).count()==1
    product(agent,'Loft');text='Tell me about Loft'
    agent.turn(text,typed(text,[req('p','property_details',text,ref='p')],[ref('p','property','Loft')]))
    data=snapshot(agent.db,agent.conversation);assert data['current_interest']['property']=='Loft' and data['appointments'][0]['property_type_name']=='Studio'
    # The enquiry changed. Explicitly request the replacement of the saved visit.
    text='I want to reschedule my visit';agent.turn(text,change(text))
    assert latest(agent).metadata_json.get('reschedule_offer')
    agent.turn('1',typed('1',[req('pick','appointment','1',ref='s')],[ref('s','appointment','1')]))
    agent.turn('Yes',understanding('Yes','other'));replacement=agent.db.query(SalesRescheduleOperation).one()
    current=agent.db.get(Meeting,replacement.replacement_meeting_id);agent.db.refresh(original)
    assert original.status==MeetingStatus.CANCELLED and current.status==MeetingStatus.CONFIRMED
    text='Cancel my visit';agent.turn(text,cancellation(text));assert latest(agent).metadata_json.get('cancellation_confirmation')
    inbound,_=agent.turn('Yes',understanding('Yes','other'));agent.retry(inbound);agent.db.refresh(current)
    assert current.status==MeetingStatus.CANCELLED and agent.db.query(SalesCancellationOperation).count()==1
    agent.turn('Give me information',understanding('Give me information','catalog'))
    assert not agent.conversation.is_paused and not agent.lead.is_opt_out and agent.lead.consent_status=='granted'
    assert agent.db.query(SalesWaitRequest).count()==1 and agent.db.query(Meeting).count()==2
    assert load(agent.db,agent.scope)[1].cadence_status=='stopped'


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_replacement_receipt_survives_a_new_session_and_failed_dispatch(agent,channel):
    from sqlalchemy.orm import Session
    from test_sales_ai_group_g import prepare
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.models import SalesConversation
    agent.conversation.channel=channel;original=prepare(agent)
    agent.send.side_effect=RuntimeError('Synthetic uncertain dispatch')
    with pytest.raises(RuntimeError):agent.turn('Yes',understanding('Yes','other'))
    operation=agent.db.query(SalesRescheduleOperation).one();saved=(operation.id,operation.replacement_meeting_id)
    message=agent.db.query(SalesMessage).filter_by(direction='inbound',content='Yes').order_by(SalesMessage.created_at.desc()).first();message_id=message.id;calls=agent.infer.await_count
    bind=agent.db.get_bind();agent.db.close();agent.db=Session(bind)
    try:
        scope=agent.scope;agent.company=agent.db.get(Company,scope.company_id);agent.project=agent.db.get(Project,scope.project_id)
        agent.lead=agent.db.get(Lead,scope.lead_id);agent.conversation=agent.db.get(SalesConversation,scope.conversation_id)
        agent.send.side_effect=lambda *a,**kw:{'sid':'synthetic-restarted','status':'sent'}
        agent.retry(agent.db.get(SalesMessage,message_id))
        operation=agent.db.query(SalesRescheduleOperation).one()
        assert (operation.id,operation.replacement_meeting_id)==saved and agent.infer.await_count==calls
        assert agent.db.query(Meeting).count()==2 and not agent.conversation.is_paused
    finally:agent.db.close()


def request():return {'model':MODEL,'messages':[{'role':'system','content':'Closed schema only'},{'role':'user','content':'Hello'}],'schema':{'type':'object','properties':{},'additionalProperties':False}}


def test_probe_uses_fixed_model_endpoint_schema_price_and_token_limits_without_private_reasoning():
    def handler(req):
        assert str(req.url)=='https://openrouter.ai/api/v1/chat/completions'
        body=json.loads(req.content);assert body['model']==MODEL and body['max_tokens']==2048
        assert not body['provider']['allow_fallbacks'] and body['provider']['require_parameters']
        assert body['provider']['max_price']=={'prompt':1,'completion':2,'request':0}
        return httpx.Response(200,json={'model':MODEL,'choices':[{'finish_reason':'stop','message':{'content':'{}','reasoning':'DO NOT EXPORT'}}],'usage':{'prompt_tokens':20,'completion_tokens':2,'cost':.0001}})
    result=probe(request(),'SYNTHETIC_KEY',transport=httpx.MockTransport(handler))
    assert result['text']=='{}' and 'DO NOT EXPORT' not in str(result) and 'SYNTHETIC_KEY' not in str(result)


@pytest.mark.parametrize('status',[301,401,429,500])
def test_probe_refuses_redirects_and_provider_errors_without_logging_bodies(status):
    calls=[]
    def handler(req):calls.append(req);return httpx.Response(status,json={'error':'PRIVATE PROVIDER BODY'},headers={'Location':'https://example.invalid/steal'})
    with pytest.raises(RuntimeError,match='OpenRouterHTTP'+str(status)):
        probe(request(),'SYNTHETIC_KEY',transport=httpx.MockTransport(handler))
    assert len(calls)==1


@pytest.mark.parametrize('change',[{'model':'another/model'},{'messages':[{'role':'tool','content':'x'}]}])
def test_probe_rejects_unapproved_model_or_message_roles(change):
    with pytest.raises(ValueError):payload({**request(),**change})


def test_budget_is_reserved_before_calls_and_retains_uncertain_cost():
    budget=Budget(1,1);_,record=budget.reserve(request());assert budget.reserved>0 and record['status']=='started'
    with pytest.raises(EvaluationBudgetExceeded):budget.reserve(request())
    assert len(budget.records)==1 and budget.stop_reason=='budget_exhausted'
    with pytest.raises(ValueError):Budget(20,float('nan'))
    with pytest.raises(ValueError):Budget(501,1)
    with pytest.raises(ValueError):Budget(20,11)


def test_too_small_budget_or_oversized_payload_never_reserves_a_call():
    budget=Budget(2,.00000001)
    with pytest.raises(EvaluationBudgetExceeded):budget.reserve(request())
    assert not budget.records
    with pytest.raises(ValueError):Budget(2,1).reserve({**request(),'messages':[{'role':'user','content':'x'*(MAX_BYTES+1)}]})


def test_pack_copy_excludes_credentials_and_runtime_and_preserves_source(tmp_path):
    path=tmp_path/'pack.json';data={'model':MODEL,'system_prompt':'Approved identity','openrouter_api_key':'PRIVATE','runtime_config':{'mode':'active'}}
    path.write_text(json.dumps(data));before=path.read_bytes();pack=load_pack(path)
    assert pack=={'model':MODEL,'system_prompt':'Approved identity'} and path.read_bytes()==before


def test_real_command_without_a_key_records_blocked_not_model_quality(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY',raising=False);pack=tmp_path/'pack.json';pack.write_text(json.dumps({'model':MODEL}))
    catalog=Path(__file__).parent/'fixtures/sales_ai/synthetic_catalog.json';output=tmp_path/'blocked.json'
    assert main(['--mode','real','--agent-pack',str(pack),'--catalog',str(catalog),'--output',str(output),'--budget-usd','1'])==2
    report=json.loads(output.read_text());assert report['status']=='BLOCKED' and not report['model_quality_evaluated'] and not report['calls']


def test_summary_keeps_real_and_synthetic_separate_and_reports_semantic_variation():
    results=[{'id':'x','origin':'REAL_APPROVED','channel':'sms','passed':True,'failures':[]},
        {'id':'x','origin':'REAL_APPROVED','channel':'sms','passed':False,'failures':['ordinal_binding']},
        {'id':'x','origin':'SYNTHETIC','channel':'sms','passed':True,'failures':[]}]
    summary=summarize(results,[{'elapsed_ms':100},{'elapsed_ms':200}])
    assert summary['by_origin']['REAL_APPROVED']=={'executed':2,'passed':1}
    assert summary['repeat_consistency'][0]['semantic_outcomes_vary']
    assert summary['latency_ms']=={'p50':150,'p95':200}


def test_cancelling_inference_kills_the_child_and_retains_reserved_cost(monkeypatch):
    class Process:
        returncode=None;killed=False;waited=False
        async def communicate(self,data):raise asyncio.CancelledError()
        def kill(self):self.killed=True;self.returncode=-9
        async def wait(self):self.waited=True
    process=Process()
    async def spawn(*args,**kw):return process
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);budget=Budget(2,1)
    with pytest.raises(asyncio.CancelledError):asyncio.run(budget(MODEL,request()['messages'],request()['schema']))
    assert process.killed and process.waited and budget.reserved>0
    assert budget.records[0]['status']=='failed_or_uncertain' and budget.records[0]['error_code']=='CancelledError'


def test_offline_postgres_wrapper_rejects_non_test_database_before_starting_python():
    root=Path(__file__).resolve().parents[1];env={**os.environ,'BP_PYTHON':sys.executable,'BP_POSTGRES_TEST_URL':'postgresql://localhost/production'}
    result=subprocess.run(['bash',str(root/'tools/sales_ai/offline.sh'),'group-k'],env=env,capture_output=True,text=True)
    assert result.returncode==2 and 'Refusing a non-test' in result.stderr


def test_real_journey_harness_can_inject_contracts_without_reaching_a_network(monkeypatch):
    from sales_ai_support.sandbox import load_catalog
    class ScriptedBudget(Budget):
        async def __call__(self,model,messages,schema):
            _,record=self.reserve({'model':MODEL,'messages':messages,'schema':schema});record['status']='scripted'
            context=json.loads(messages[-1]['content'])
            if 'evidence_blocks' in context:
                return json.dumps({'version':'sales-commercial-composer/1.0','opening':'direct','blocks':[{'evidence_id':b['id'],'wording':'direct'} for b in context['evidence_blocks'] if b['required']], 'continuation_id':context['continuations'][0]['id']})
            text=context['current_message'];return understanding(text,'catalog').model_dump_json()
    catalog=load_catalog('synthetic_catalog.json');case=next(c for c in scenarios(catalog) if c['kind']=='catalog')
    result=run_case(catalog,case,'sms',1,{'model':MODEL},ScriptedBudget(20,2))
    assert result['passed'],result
    assert result['model_calls']>0 and result['commercial_human_review']=='PENDING'


def test_acceptance_coverage_references_real_tests_and_never_claims_live_acceptance():
    import ast
    root=Path(os.environ.get('SALES_ACCEPTANCE_ROOT') or Path(__file__).resolve().parents[2]);coverage=json.loads((root/'backend/tests/fixtures/sales_ai/group_k_coverage.json').read_text())
    assert {c['id'] for c in coverage['cases']}=={f'T{i:02}' for i in range(1,27)}
    assert not coverage['complete_T01_T26_acceptance']
    for case in coverage['cases']:
        assert case['status']=='AUTOMATED_PARTIAL_NOT_FINAL_ACCEPTANCE' and not case['model_quality_evaluated']
        for ref in case['automated_partial_evidence']:
            file,name=ref.split('::');tree=ast.parse((root/file).read_text())
            assert name in {node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_signed_delivery_callbacks_are_idempotent_and_late_events_cannot_regress_receipts(agent,channel):
    import base64,time,uuid
    from fastapi import FastAPI
    from app.db.postgres import get_db
    from app.core.secret_store import encrypt_secret
    from app.modules.system_settings.models import TelnyxConfig
    from app.modules.sales_agent.models import ExternalWebhookEvent,OutboundMessage
    from app.modules.sales_agent.provider_router import telnyx_router
    from test_telnyx_messaging import _public_key
    private,public=_public_key();agent.conversation.channel=channel
    agent.db.add(TelnyxConfig(api_key_ciphertext=encrypt_secret('SYNTHETIC_KEY'),webhook_public_key=public,verification_status='verified'))
    row=SalesMessage(conversation_id=agent.conversation.id,channel=channel,direction='outbound',role='assistant',content='Synthetic confirmation',provider_message_id='test-receipt',status='sent')
    operation=OutboundMessage(conversation_id=agent.conversation.id,idempotency_key='test-callback-receipt',channel=channel,provider='telnyx',content=row.content,provider_message_id='test-receipt',status='sent')
    agent.db.add_all([row,operation]);agent.db.commit()
    app=FastAPI();app.include_router(telnyx_router,prefix='/webhooks/telnyx');app.dependency_overrides[get_db]=lambda:agent.db
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            async def callback(event_id,status,tampered=False):
                body=json.dumps({'data':{'id':event_id,'event_type':'whatsapp.message.finalized' if channel=='whatsapp' else 'message.finalized','payload':{'id':'test-receipt','to':[{'status':status}],'errors':[]}}}).encode()
                stamp=str(int(time.time()));sig=base64.b64encode(private.sign(stamp.encode()+b'|'+body)).decode()
                return await client.post('/webhooks/telnyx/messaging',content=body+b' ' if tampered else body,headers={'Content-Type':'application/json','telnyx-signature-ed25519':sig,'telnyx-timestamp':stamp})
            assert (await callback('delivered','delivered')).status_code==200
            assert (await callback('delivered','delivered')).status_code==200
            for status in ['sent','queued','failed']:assert (await callback('late-'+status,status)).status_code==200
            agent.db.refresh(row);assert row.status=='delivered'
            assert (await callback('read','read')).status_code==200
            assert (await callback('late-delivered','delivered')).status_code==200
            assert (await callback('tampered','failed',True)).status_code==401
    asyncio.run(exercise());agent.db.refresh(row);agent.db.refresh(operation)
    assert row.status==operation.status=='read' and agent.db.query(ExternalWebhookEvent).filter_by(external_event_id='delivered').count()==1
    assert not agent.db.query(Meeting).count() and agent.db.query(SalesMessage).count()==1
