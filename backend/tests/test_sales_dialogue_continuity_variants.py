"""Varied contextual reads and slot selections, never direct booking authority."""
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
import pytest
from app.modules.sales_agent.understanding_contract import Understanding,DialogueState
from app.modules.sales_agent.dialogue_continuity import normalize
from app.modules.sales_agent.interpretation_consistency import normalize as consistent
from app.modules.sales_agent.first_booking import contextual_public_selection,VERSION
from app.modules.sales_agent.language_policy import detect
from test_sales_active_integration import understanding


def previous(meta,status='sent'):
    return SimpleNamespace(metadata_json=meta,status=status,role='assistant',provider_message_id='receipt')

@pytest.mark.parametrize('text',['3?','3 bedrooms','4 bedrooms!','2'])
def test_bedroom_answers_use_only_current_needs_question(text):
    u=understanding(text,'catalog',confidence=.9)
    fixed,notes=normalize(u,text,DialogueState(),previous({'needs_search':{'bedrooms':1}}))
    assert fixed.preferences[0].value==text[0] and fixed.comparison is None
    assert fixed.confidence==.9 and notes
    if 'bedroom' not in text:assert normalize(u,text,DialogueState(),previous({}))[0]==u
    assert normalize(u,text,DialogueState(),previous({'needs_search':{}},'failed'))[0]==u

@pytest.mark.parametrize('text',['Do you have photos of the property?','Show me the property blueprints','I want to check blueprints','Please send pictures','Show me floor plans'])
@pytest.mark.parametrize('property_id',['fictional-alder','fictional-orion'])
def test_material_owner_is_active_subject_without_any_new_visit(text,property_id):
    u=understanding(text,'materials')
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id=property_id),previous({}))
    assert fixed.requests[0].topic.value=='materials' and fixed.references[0].expression=='this property'
    assert fixed.visit is None and notes and fixed.confidence==u.confidence
    if 'bedroom' not in text:assert normalize(u,text,DialogueState(),previous({}))[0]==u

@pytest.mark.parametrize('name',['Alder Cottage','Orion Duplex','Maple Terrace'])
@pytest.mark.parametrize('prefix',['I want to visit ','I would like to visit ','Please schedule a visit to '])
def test_visit_has_an_executable_request_without_invented_comparison(name,prefix):
    text=prefix+name;data=understanding(text,'catalog').model_dump(mode='json')
    data['comparison']=dict(request_id='r0',reference_ids=[],include_current=True,include_all=False,all_kind='property',criteria=['general'],operation='compare',evidence=text)
    u=Understanding.model_validate(data)
    fixed,notes=consistent(u,text,{'property_types':[{'property_type':name}]})
    assert fixed.permits('appointment') and fixed.comparison is None and fixed.visit.action=='request'
    assert fixed.confidence==u.confidence


def offer(count=1):
    return {'version':VERSION,'preferences':{'timezone':'America/Denver'},'options':[{'starts_at':f'2026-11-16T{17+i:02}:00:00+00:00','specialist_name':'Fictional Seller'} for i in range(count)]}

@pytest.mark.parametrize('text',['16 november, 10am','November 16th at 10 a.m.','16/11, 10am','Yes, that time works for me','Yes'])
def test_unique_current_time_selection_never_implies_booking(text):
    result=contextual_public_selection(text,offer())
    assert result and result['id']==offer()['options'][0]['starts_at']

@pytest.mark.parametrize('text',['Yes','No','My friend said yes','If 10am is available','16/11, 11am','16/12, 10am','16/11, 10am and cancel my visit'])
def test_unoffered_ambiguous_or_mixed_reply_is_not_selected(text):
    assert contextual_public_selection(text,offer(2) if text=='Yes' else offer()) is None

@pytest.mark.parametrize('text',['16 november, 10am','November 16th at 10 a.m.','December 1st, 9pm','January 3 at 8am'])
def test_english_months_are_not_classified_as_foreign_language(text):
    assert not detect(text).needs_reentry

@pytest.mark.parametrize('text',['I want to visit Orion Duplex','Please schedule a visit for next Monday at 10 a.m.'])
def test_absent_timezone_is_not_replaced_with_the_whole_sentence(text):
    data=understanding(text,'appointment').model_dump(mode='json')
    data['visit']=dict(action='request',evidence=text,timing=dict(timezone_evidence=text))
    fixed,notes=normalize(Understanding.model_validate(data),text,DialogueState(),previous({}))
    assert fixed.visit.timing.timezone_evidence is None
    assert fixed.confidence==data['confidence']

@pytest.mark.parametrize('text',['I do not want a visit','If I want to visit Alder Cottage','My friend said visit Alder Cottage'])
def test_negative_conditional_and_reported_speech_do_not_gain_an_action(text):
    u=understanding(text,'catalog')
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id='alder'),previous({}))
    assert fixed==u and not notes

@pytest.mark.parametrize('text',['How does this property differ from the others?','What are the differences with the other properties for this property?'])
def test_explicit_comparison_can_use_current_subject_without_selecting_a_new_one(text):
    u=understanding(text,'catalog')
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id='orion'),previous({}))
    assert fixed.comparison and fixed.comparison.include_current and fixed.comparison.include_all
    assert fixed.selected_reference_id is None and fixed.visit is None


def test_bare_number_after_catalog_is_not_reinterpreted_as_bedrooms():
    u=understanding('3','catalog')
    fixed,notes=normalize(u,'3',DialogueState(),previous({'needs_search':{'bedrooms':2},'property_catalog_offer':{'property_type_ids':['a','b','c']}}))
    assert not any(p.key=='bedrooms' for p in fixed.preferences)
    assert fixed.requests[0].id=='current_choice'

@pytest.mark.parametrize('text',['2','property 2','The property 2','Give me more information about property 2'])
def test_zero_confidence_numbered_choice_only_permits_a_verified_read(text):
    from app.modules.sales_agent.dialogue_continuity import catalog_choice_read
    latest=previous({'property_catalog_offer':{'property_type_ids':['a','b']}})
    u=understanding(text,'catalog',confidence=0)
    fixed,notes=normalize(u,text,DialogueState(),latest)
    assert fixed.confidence==0 and catalog_choice_read(fixed,text,latest,{'property_types':[{'id':'a'},{'id':'b'}]})
    assert not catalog_choice_read(fixed,text,previous({}),{'property_types':[{'id':'b'}]})
    partial=previous({'property_catalog_offer':{'property_type_ids':['a','b']},'delivery_group':{'total':2}})
    assert not catalog_choice_read(fixed,text,partial,{'property_types':[{'id':'a'},{'id':'b'}]})
    assert not catalog_choice_read(fixed,text,latest,{'property_types':[{'id':'a'}]})

@pytest.mark.parametrize('name',['Alder Cottage','Orion Duplex','Maple Terrace'])
def test_named_choice_does_not_carry_invented_comparison_or_timing(name):
    data=understanding(name,'catalog').model_dump(mode='json')
    data['comparison']=dict(request_id='r0',reference_ids=[],include_current=True,include_all=False,all_kind='property',criteria=['general'],operation='compare',evidence=name)
    data['visit']=dict(action='request',evidence=name,timing=dict(timezone_evidence=name))
    fixed,notes=consistent(Understanding.model_validate(data),name,{'property_types':[{'property_type':name}]})
    assert fixed.comparison is None and fixed.visit is None and fixed.selected_reference_id
    assert fixed.confidence==data['confidence']


def test_comparison_recovery_preserves_independent_visit_request():
    text='How does this property differ from the others? I want to schedule a visit.'
    u=understanding(text,'catalog','appointment').model_copy(update={'visit':None})
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id='alder'),previous({}))
    assert len(fixed.requests)==2 and any(r.topic.value=='appointment' for r in fixed.requests)
