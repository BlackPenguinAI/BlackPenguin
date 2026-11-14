"""Transfer vocabulary and closed guards for comparison, switching and assent."""
from types import SimpleNamespace
import pytest
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.interpretation_consistency import normalize
from app.modules.sales_agent.first_booking import enrich_understanding

@pytest.mark.parametrize('name',['Alder Cottage','Orion Duplex','Maple Terrace'])
@pytest.mark.parametrize('phrase',['Actually I prefer {} instead.','I choose {}.','I would like {} instead.','I\'d prefer {}.','I\'ll take {}.'])
def test_own_single_property_preference_changes_subject_without_comparing(name,phrase):
    text=phrase.format(name);data=understanding(text,'catalog').model_dump(mode='json')
    data['references']=[dict(id='a',kind='property',expression='Old Home',evidence=text),dict(id='b',kind='property',expression=name,evidence=text)]
    data['comparison']=dict(request_id='r0',reference_ids=['a','b'],include_current=True,include_all=False,all_kind='property',criteria=['general'],operation='compare',evidence=text)
    fixed,notes=normalize(Understanding.model_validate(data),text,{'property_types':[{'property_type':'Old Home'},{'property_type':name}]})
    assert fixed.comparison is None and len(fixed.references)==1 and fixed.references[0].expression==name
    assert fixed.selected_reference_id==fixed.references[0].id and fixed.visit is None
    assert fixed.confidence==data['confidence']

@pytest.mark.parametrize('text',['If I prefer Alder Cottage instead.','My friend said I prefer Alder Cottage.','I prefer Alder Cottage or Old Home.','I prefer Alder Cottage. Cancel my visit.'])
def test_mixed_conditional_or_reported_preference_is_not_rewritten(text):
    u=understanding(text,'catalog')
    fixed,notes=normalize(u,text,{'property_types':[{'property_type':'Alder Cottage'},{'property_type':'Old Home'}]})
    assert fixed.selected_reference_id is None and fixed.visit is None

@pytest.mark.parametrize('text',['Yes','Yes please','Confirmed','That works'])
def test_current_summary_acceptance_clears_placeholder_reference_but_preserves_confidence(text):
    data=understanding(text,'appointment').model_dump(mode='json')
    data['references']=[dict(id='bad',kind='appointment',expression='/',evidence=text)]
    data['requests'][0]['reference_id']='bad'
    fixed=enrich_understanding(Understanding.model_validate(data),{'booking_confirmation':{'id':'current-proposal'}},text)
    assert fixed.visit and fixed.visit.action=='confirm' and fixed.visit.timing is None
    assert not fixed.references and fixed.confidence==data['confidence']
    assert enrich_understanding(Understanding.model_validate(data),{},text).references

@pytest.mark.parametrize('meta',[{'material_offer':{}},{'booking_confirmation':{'id':'p'},'material_offer':{'id':'asset'}},{'booking_confirmation':{'id':'p'},'release_offer':{'id':'hold'}}])
def test_other_offer_does_not_grant_summary_acceptance(meta):
    u=understanding('Yes','appointment')
    assert enrich_understanding(u,meta,'Yes').visit is None
