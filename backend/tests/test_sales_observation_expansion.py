"""Runner and strict-check validation; mocks do not certify model dialogue quality."""
import asyncio,json
from unittest.mock import patch
import httpx,pytest
from test_sales_booking_pilot import lab
from test_sales_continuity_battery import provider
from tools.sales_ai.observation_battery import BASELINE_CASES,ALL_CASES,EXPANSION,evaluate_case
from tools.sales_ai.observation_expanded_checks import turn_checks
from tools.sales_ai.evaluation_guard import Budget,guard
from app.modules.ai_core.models import AIConfiguration,PromptVersion

def test_stable_six_and_nine_new_capabilities():
    assert len(BASELINE_CASES)==6 and len(ALL_CASES)==15 and len(EXPANSION)==9
    assert not set(BASELINE_CASES)&set(EXPANSION)
    assert {s['group'] for s in EXPANSION.values()}=={'materials','consultative','preferences','appointment','continuity'}

def test_bare_delivery_and_unanswered_acceptance_fail():
    rows=[dict(action='material',reply='PDF: link',metadata={'material_bindings':[{'binding':{'mime_type':'application/pdf'}}]}),dict(action='accept_material',reply='What do you want?',metadata={})]
    assert all(any(c['status']=='FAIL' for c in turn_checks(row,'ext_gallery_pdf')) for row in rows)

@pytest.mark.parametrize('key',EXPANSION)
def test_nine_scripts_execute_and_export_honest_failures(lab,key):
    db,manifest=lab
    db.add(AIConfiguration(id='expansion-offline',company_id=None,openrouter_api_key='OFFLINE',agent_ventas={'model':'test/offline'}))
    db.add(PromptVersion(company_id=None,agent_key='sales',version_number=1,is_published=True,configuration={'model':'test/offline'}));db.commit()
    original=httpx.AsyncClient
    class Client(original):
        def __init__(self,**kwargs):super().__init__(transport=httpx.MockTransport(provider),trust_env=False,**kwargs)
    budget=Budget(100)
    with patch.object(httpx,'AsyncClient',Client),guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
        result=asyncio.run(evaluate_case(db,manifest,key,budget,20))
    assert result['cohort']=='expanded-nine' and result['turns'] and result['review_required']
    assert result['overall_dialogue_quality']=='NOT_EVALUATED'
    assert all(c['status'] in {'PASS','FAIL','BLOCKED'} for c in result['checks'])
