"""Observed sparse provider frames must not erase current scoped subjects."""
import asyncio,json,re
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from test_sales_booking_pilot import lab
from test_sales_compact_battery import provider
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.understanding_completeness import scoped_subjects,completeness_issues
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from tools.sales_ai.compact_battery import CASES,evaluate_case,returns_gap_answered
from tools.sales_ai.evaluation_guard import Budget,guard

CAPTURE=json.loads((Path(__file__).parent/'fixtures/sales_ai/compact_battery_1_interpretations.json').read_text())['rows']
CONTEXT={'property_types':[{'property_type':n} for n in ['Cedar Loft','Cedar Studio','Ridge Townhome','Summit Villa','Valley Apartment','Bay Residence']]}

@pytest.mark.parametrize('row',[r for r in CAPTURE if any(name in r['text'] for name in ['Cedar Studio','Ridge Townhome','Cedar Loft','Valley Apartment']) and 'compare' not in r['text'].lower()],ids=lambda r:r['case']+'-'+r['text'][:18])
def test_recorded_sparse_frames_retain_exact_scoped_subject(row):
    value=Understanding.model_validate(row['understanding']);fixed,notes=scoped_subjects(value,row['text'],CONTEXT)
    relevant=[r for r in fixed.requests if r.polarity=='request' and r.topic.value in {'inventory','catalog','materials','pricing','appointment'}]
    if relevant:
        assert any(r.reference_id for r in relevant)
        assert any(r.kind=='property' and r.evidence in row['text'] for r in fixed.references)
    assert fixed.visit==value.visit and fixed.preferences==value.preferences
    assert scoped_subjects(fixed,row['text'],CONTEXT)[0]==fixed

@pytest.mark.parametrize('text',["Send photos of Cedar Loft and Cedar Studio.","My friend said send photos of Cedar Studio.","Do not send photos of Cedar Studio.","If I wanted Cedar Studio, would it be suitable?","Send photos of Cedar Studios."])
def test_ambiguity_negation_reporting_and_similar_names_do_not_gain_a_binding(text):
    u=understanding(text,'materials',subjects={0:'photos'})
    fixed,notes=scoped_subjects(u,text,CONTEXT)
    assert fixed==u and not notes

@pytest.mark.parametrize('text',["I am buying my first home.","I want to move from my current small home to a larger home.","I am relocating for work.","I want to downsize.","I am buying an investment property to earn rental income.","I am investing for appreciation and later resale.","I want to diversify my investment portfolio."])
def test_own_purpose_omission_gets_bounded_feedback(text):
    issues=completeness_issues(understanding(text,'other'),text)
    assert any(i['type']=='own_purchase_purpose_missing' for i in issues)

@pytest.mark.parametrize('text',["My friend said I am buying my first home.","If I am buying my first home, what then?","I am not buying my first home.","I am a 42-year-old engineer."])
def test_no_segment_inferred_from_reported_hypothetical_negative_or_demographic_fact(text):
    assert not any(i['type']=='own_purchase_purpose_missing' for i in completeness_issues(understanding(text,'other'),text))

@pytest.mark.parametrize('name',['Summit Villa','Cedar Studio','Ridge Townhome','Parque del Sol'])
def test_scoped_names_do_not_turn_english_questions_into_foreign_language(name):
    from app.modules.sales_agent.language_policy import detect
    assert not detect('Is '+name+' available?',names=[name]).needs_reentry
    assert detect('Quiero conocer el precio de '+name,names=[name]).needs_reentry


def test_return_audit_cannot_match_rent_inside_current_or_accept_loan_disclaimer():
    assert not returns_gap_answered('The current availability needs confirmation. Financing approval is not determined in this chat.')
    assert returns_gap_answered('I do not have published rental yield or occupancy figures.')
    from test_sales_commercial_policy_v2 import advise,buyer
    mixed='What rental yield is published, and what financing options are available?'
    result=advise(mixed,lead=buyer(),u=understanding(mixed,'other','financing'))
    assert result['decision']=='investment_information'
    assert 'budget' not in result['closing']
    assert returns_gap_answered(' '.join(result['blocks']))
    text='What annual rental yield or occupancy can you guarantee?'
    assert any(i['type']=='investment_return_as_financing' for i in completeness_issues(understanding(text,'financing'),text))


@pytest.mark.parametrize('scenario',CASES)
def test_observed_omissions_repair_through_actual_core_and_all_expected_bookings(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='repair-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    seen={};recorded={r['text']:r['understanding'] for r in CAPTURE if r['case']==scenario}
    def response(request):
        payload=json.loads(request.content);ctx=json.loads(payload['messages'][1]['content']);text=ctx['current_message']
        if payload['response_format']['json_schema']['name']=='sales_understanding':
            seen[text]=seen.get(text,0)+1
            # Replay actual recorded first response. The repair provider then
            # satisfies the protocol; no tools, profile or scheduling is mocked.
            if seen[text]==1 and text in recorded:
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(recorded[text])}}]})
        return provider(request)
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(response),trust_env=False,**kwargs)
    budget=Budget(40)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    failures=[(t['action'],t.get('reply'),c) for t in result['turns'] for c in t['checks'] if c['status']=='FAIL']
    failures += [('final','',c) for c in result['checks'] if c['status']=='FAIL']
    assert not failures,failures
    assert len(result['meetings'])==(1 if scenario.endswith('_A') else 0)


def test_reported_catalog_name_and_individual_unit_are_not_promoted_to_typology():
    for text,context in [("You said send photos for Cedar Studio.",CONTEXT),
                         ("Show me Cedar Studio-A1.",{**CONTEXT,'inventory':[{'unit_code':'Cedar Studio-A1'}]})]:
        value=understanding(text,'inventory')
        assert scoped_subjects(value,text,context)==(value,[])
