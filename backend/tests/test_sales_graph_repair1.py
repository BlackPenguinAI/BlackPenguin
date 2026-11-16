"""Integrated server failures + transfer variants. All remote providers mocked."""
import asyncio,json
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
import pytest,httpx
from test_sales_booking_pilot import lab
from test_sales_active_integration import understanding
from test_sales_observation_loop import provider as base_provider
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.interpretation_input import compile_input
from tools.sales_ai.observation_battery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard

RECORD=json.loads((Path(__file__).parent/'fixtures/sales_graph_repair1/server_frames.json').read_text())
FAILED=next(c for c in RECORD['cases'] if c['case']=='obs_alternative')['turns'][-1]['interpretation_attempts']


def recorded_provider(scenario,visit_attempt=0):
    case=next(c for c in RECORD['cases'] if c['case']==scenario)
    def provider(request):
        payload=json.loads(request.content)
        if payload['response_format']['json_schema']['name']!='sales_understanding':return base_provider(request)
        text=json.loads(payload['messages'][1]['content'])['current_message']
        row=next((t for t in case['turns'] if t['lead_message']==text),None)
        if not row:return base_provider(request)
        frames=row['interpretation_attempts'] or []
        if not frames:return base_provider(request)
        raw=frames[min(visit_attempt,len(frames)-1)]['raw_response'] if row['runtime_error'] else frames[-1]['raw_response']
        return httpx.Response(200,json={'choices':[{'message':{'content':raw}}]})
    return provider


@pytest.mark.parametrize('scenario,attempt',[(c,0) for c in CASES]+[('obs_alternative',1)])
def test_current_server_frames_reach_safe_goals_on_integrated_graph(lab,scenario,attempt,tmp_path):
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    db,manifest=lab
    db.add(AIConfiguration(id='graph-repair',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(recorded_provider(scenario,attempt)),trust_env=False,**kwargs)
    budget=Budget(150)
    with guard(budget),patch.object(httpx,'AsyncClient',Client),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kwargs:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,10))
    (tmp_path/'result.json').write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2))
    assert not [c for t in result['turns'] for c in t['checks'] if c['status']!='PASS']
    assert not [c for c in result['checks'] if c['status']!='PASS']
    assert all(t['coordinator_graph']['mode']=='graph-observe' for t in result['turns'])
    if scenario=='obs_mixed':
        t=next(t for t in result['turns'] if t['action']=='material')
        assert t['observation_loop']['source_request_coverage']['status']=='PASS'
        assert t['observation_loop']['source_request_coverage']['required'] is True
        assert any(r['topic']=='financing' for r in t['understanding']['requests'])
    if scenario=='obs_alternative':
        assert len(result['meetings'])==1
        assert not any('photo coverage' in t['reply'] for t in result['turns'])
    for t in result['turns']:
        if t['metadata'].get('appointment_offer'):
            assert 'America/' not in t['reply'] and 'UTC-0' not in t['reply']


@pytest.mark.parametrize('owner',['Juniper Home','Maple Residence','Harbor Flat'])
@pytest.mark.parametrize('phrase',['Can I visit {name}?','Could we view {name}?','Please schedule a visit to {name}.','Fine. I would like to visit {name}.'])
@pytest.mark.parametrize('attempt',[0,1])
def test_pure_visit_variants_replace_invented_comparisons_without_confirming(owner,phrase,attempt):
    text=phrase.format(name=owner);raw=json.loads(FAILED[attempt]['raw_response'])
    u,notes=compile_input(json.dumps(raw),text)
    assert u.visit.action=='request' and u.permits('appointment') and u.comparison is None
    assert u.confidence==raw['confidence'] and not u.alternatives
    assert u.references[0].expression==owner and u.references[0].evidence==owner
    assert any(n['action']=='literal_visit_not_comparison' for n in notes)


@pytest.mark.parametrize('text',[
    'Do not visit Juniper Home.','If I wanted to visit Juniper Home?','My friend said: Can I visit Juniper Home?',
    'Can I visit Juniper Home or Maple Residence?','Can I visit Juniper Home and explain financing?',
    'Compare Juniper Home and Maple Residence.','Cancel my visit to Juniper Home.','Reschedule my visit to Juniper Home.',
    'Yes, book it.','Can I visit Juniper Home tomorrow at 10 AM?',
])
def test_visit_repair_never_collapses_conditions_questions_or_confirmation(text):
    from app.modules.sales_agent.interpretation_wire_repairs import literal_visit
    raw=json.loads(FAILED[0]['raw_response']);fixed,notes=literal_visit(raw,text)
    assert fixed==raw and not notes


@pytest.mark.parametrize('text',[
    'Send photos or a brochure and explain the financing options?',
    'Explain financing and send photos or a PDF.',
    'Could you explain the payment methods?',
    'What financing options do you offer?',
    'Show blueprints; tell me about mortgage plans.',
    'Share the PDF. What are the loan options?',
])
def test_independent_financing_question_is_read_not_preference_or_material_or(text):
    from app.modules.sales_agent.request_coverage import normalize,issues
    value=understanding(text,'materials',subjects={0:'brochure'},confidence=.9)
    assert issues(value,text)
    fixed,notes=normalize(value,text)
    finance=next(r for r in fixed.requests if r.topic.value=='financing')
    assert finance.id in fixed.all_of and not issues(fixed,text) and not fixed.preferences
    assert fixed.visit is None and fixed.confidence==.9 and notes
    assert finance.evidence in text


@pytest.mark.parametrize('text',[
    'I have cash.','I will pay outright.','I do not need financing.','No financing questions.',
    'My friend asked: What financing options do you offer?','If I need a loan, what happens?',
    'Please do not explain the financing options.','Explain financing for Unknown Tower.',
])
def test_coverage_does_not_create_questions_from_declarations_negation_or_unknown_owners(text):
    from app.modules.sales_agent.request_coverage import normalize,issues
    value=understanding(text,'other');fixed,notes=normalize(value,text)
    assert fixed==value and not notes and not issues(fixed,text)


def test_financing_cannot_disappear_inside_material_alternatives():
    from app.modules.sales_agent.request_coverage import issues
    text='Send photos or a brochure and explain financing'
    value=understanding(text,'materials','financing',alternatives=True)
    assert issues(value,text)[0]['type']=='independent_financing_question_in_material_or'


@pytest.mark.parametrize('zone',['America/New_York','America/Chicago','America/Denver','Europe/London'])
def test_friendly_time_labels_preserve_exact_public_selection_and_old_receipts(zone):
    from app.modules.sales_agent.first_booking import label,public_label,exact_public_selection,VERSION
    option={'starts_at':'2026-11-20T15:00:00+00:00','specialist_name':'Synthetic Advisor'}
    prefs={'timezone':zone};offer={'version':VERSION,'options':[option],'preferences':prefs}
    for render in (label,public_label):
        selected=exact_public_selection('I would like the first appointment: '+render(option,prefs),offer)
        assert selected['id']==option['starts_at']
    assert zone not in public_label(option,prefs) and 'local time' in public_label(option,prefs)
    assert exact_public_selection('Yes',offer) is None

@pytest.mark.parametrize('payment',['/','bank financing','loan','cash'])
def test_financing_policy_question_never_changes_declared_payment_preference(payment):
    from app.modules.sales_agent.request_coverage import normalize
    text='Explain the financing options?'
    raw=understanding(text,'materials',subjects={0:'brochure'}).model_dump()
    raw['preferences']=[dict(key='financing',value=payment,evidence=text,status='declared')]
    fixed,notes=normalize(Understanding.model_validate(raw),text)
    assert fixed.permits('financing') and not fixed.preferences and notes


def test_public_driver_parses_friendly_clock_without_guessing_a_different_zone():
    from tools.sales_ai.compact_battery import public_selection_time
    assert public_selection_time('2026-11-20 at 10:00 AM (New York local time); Advisor','America/New_York')==datetime(2026,11,20,15)
    assert public_selection_time('2026-11-20 at 10:00 AM (America/New_York, UTC-0500); Advisor','America/New_York')==datetime(2026,11,20,15)
    assert public_selection_time('2026-11-20 at 10:00 AM (Chicago local time); Advisor','America/New_York') is None
