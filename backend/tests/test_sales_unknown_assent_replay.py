"""Replay recorded server interpretations through the real core; offline network."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_compact_battery import provider
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.needs_search import literal_read,normalize
from app.modules.sales_agent.understanding_contract import Understanding
from tools.sales_ai.needs_discovery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

CAPTURE=json.loads((Path(__file__).parent/'fixtures/sales_ai/needs_wording_1_interpretations.json').read_text())['rows']

@pytest.mark.parametrize('scenario',[k for k in CASES if any(r['case']==k for r in CAPTURE)])
def test_recorded_wording_interpretations_preserve_filter_and_accept_low_confidence_yes(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='replay-needs',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    packets={r['message']:r['understanding'] for r in CAPTURE if r['case']==scenario}
    def replay(request):
        payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content'])
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(packets[context['current_message']])}}]})
        return provider(request)
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(replay),trust_env=False,**kwargs)
    with patch.object(httpx,'AsyncClient',Client),guard(Budget(20)),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,Budget(20),3))
    failures=[(r['lead_message'],r['reply'],c) for r in result['turns'] for c in r['checks'] if c['status']=='FAIL']
    assert not failures,failures
    if scenario=='unknown_bedrooms_accept':
        row=result['turns'][-1]
        assert row['understanding']['confidence']==0
        assert row['read_authorization']['model_confidence']==0
        assert row['read_authorization']['basis']=='accepted_current_unknown_listing_offer'
        assert row['read_authorization']['effect_authorization'] is False


@pytest.mark.parametrize('current,status,text,extra,allowed',[
    (True,'sent','Yes',{},True),
    (True,'queued','Yes',{},False),
    (False,'sent','Yes',{},False),
    (True,'sent','Yes, book a visit',{},False),
    (True,'sent','Yes',{'visit':{'action':'search','evidence':'Yes'}},False),
])
def test_low_confidence_assent_is_only_a_current_delivered_catalog_read(lab,current,status,text,extra,allowed):
    from app.modules.sales_agent.needs_search import contextual_read
    from app.modules.sales_agent.models import SalesConversation,SalesMessage
    from app.modules.sales_agent.dialogue_store import Scope
    from datetime import datetime,timedelta
    db,manifest=lab
    # Reuse the actual laboratory's scope; no live messaging is involved.
    from app.modules.sales_crm.models import Lead
    from app.modules.projects.models import Project
    project=db.query(Project).first()
    lead=Lead(company_id=project.company_id,project_id=project.id,full_name='Assent guard',phone='+15550100099',source='manual',consent_status='granted')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=lead.company_id,project_id=project.id,lead_id=lead.id,channel='sms',provider='telnyx')
    db.add(conversation);db.flush();scope=Scope(lead.company_id,project.id,conversation.id,lead.id)
    now=datetime.utcnow()
    db.add(SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='Would you like to see those homes?',status=status,created_at=now,metadata_json={'needs_unknown_offer':{'bedrooms':2,'property_ids':['unknown']}}))
    if not current:db.add(SalesMessage(conversation_id=conversation.id,channel='sms',direction='outbound',role='assistant',content='When would you like to visit?',status='sent',created_at=now+timedelta(seconds=1)))
    db.commit()
    packet=next(r['understanding'] for r in CAPTURE if r['case']=='unknown_bedrooms_accept' and r['message']=='Yes')
    value=Understanding.model_validate(packet).model_copy(update=extra)
    assert contextual_read(db,scope,value,text) is allowed
    assert value.confidence==0 and value.requires_clarification
