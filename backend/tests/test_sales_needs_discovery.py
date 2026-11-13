"""Needs-first core experiments with an offline provider; not model quality claims."""
import asyncio
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_compact_battery import provider
from test_sales_active_integration import understanding
from app.modules.ai_core.models import AIConfiguration,PromptVersion
from app.modules.sales_agent.needs_search import criterion,normalize
from tools.sales_ai.needs_discovery import CASES,evaluate_case
from tools.sales_ai.evaluation_guard import Budget,guard


@pytest.mark.parametrize('scenario',CASES)
def test_needs_first_conversations_through_current_core(lab,scenario):
    db,manifest=lab
    db.add(AIConfiguration(id='needs-config',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kwargs)
    budget=Budget(20)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,scenario,budget,8))
    failures=[(r['lead_message'],r['reply'],c) for r in result['turns'] for c in r['checks'] if c['status']=='FAIL']
    assert not failures,failures
    assert result['needs_dialogue_checks']=='PASS'


@pytest.mark.parametrize('text',["My friend said I am looking for a 2 bedroom",'If I need a 2 bedroom home, what then?',"I do not want a 2 bedroom home.",'I want at least 2 bedrooms.','I need 2 or 3 bedrooms.','How many bedrooms does Cedar Loft have?','I need a 2 bedroom home and a 3 bedroom home.'])
def test_non_exact_or_other_peoples_needs_are_not_exact_filters(text):
    assert criterion(text) is None


def test_bedroom_count_is_not_a_property_reference_or_visit_consent():
    text='I am looking for a 2 bedroom home'
    data=understanding(text,'property_details').model_dump()
    data['references']=[dict(id='p',kind='property',expression='2 bedroom',evidence='2 bedroom')]
    data['requests'][0]['reference_id']='p'
    data['requires_clarification']=True;data['clarification_question']='Which property do you mean?'
    from app.modules.sales_agent.understanding_contract import Understanding
    frame,notes=normalize(Understanding.model_validate(data),text,{'property_types':[]})
    assert frame.permits('catalog') and not frame.requires_clarification
    assert not frame.references and not frame.visit and frame.selected_reference_id is None
    assert frame.preferences[0].value=='2' and notes
    data['requests'][0]['evidence']='2 bedroom'
    shorter,_=normalize(Understanding.model_validate(data),text,{'property_types':[]})
    assert shorter.permits('catalog') and not shorter.references and not shorter.requires_clarification


def test_mixed_questions_and_named_properties_are_not_erased():
    from app.modules.sales_agent.understanding_contract import Understanding
    text='I need a 2 bedroom home. What financing is available?'
    frame=understanding(text,'catalog','financing')
    fixed,_=normalize(frame,text,{'property_types':[]})
    assert fixed.permits('catalog') and fixed.permits('financing') and fixed.visit is None
    text='I need a 2 bedroom home like Cedar Loft.'
    frame=understanding(text,'property_details')
    assert normalize(frame,text,{'property_types':[{'property_type':'Cedar Loft'}]})==(frame,[])


def test_generic_catalog_reply_is_rejected_even_when_composition_is_accepted():
    from tools.sales_ai.needs_discovery import assertions
    context={'property_types':[{'id':'p','property_type':'Cedar Loft','bedrooms':2,'available_units':1,'inventory_updated_at':'2026-01-01'}],'catalog_coverage':{'exhaustive':True}}
    checks=assertions('I need a 2 bedroom home','A lovely project. Which property option do you mean?',{'composition':{'status':'accepted'}},context,None)
    assert any(c['status']=='FAIL' for c in checks)
    assert next(c for c in checks if c['check']=='needs_filter_executed')['status']=='FAIL'


def test_retrospective_labels_preserve_original_success_but_flag_bad_dialogue():
    import importlib.util
    from pathlib import Path
    import os
    path=Path(os.environ.get('SALES_ACCEPTANCE_ROOT',Path(__file__).resolve().parents[2]))/'docs/sales-agent/06-como-ejecutar-las-pruebas/herramientas/clasificar_resultados.py'
    spec=importlib.util.spec_from_file_location('labels',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    original={'automatic_result':'aprobado','turns':[{'turn':2,'agent':'Property_details: verified information is not available in this query.'}]}
    result=module.classify(original)
    assert original['automatic_result']=='aprobado'
    assert result['recorded_checks']=='aprobado' and result['dialogue_quality']=='NEEDS_IMPROVEMENT'
    assert not result['integral_dialogue_approval']
    assert module.classify({'automatic_result':'aprobado','turns':[]})['dialogue_quality']=='NOT_EVALUATED'
