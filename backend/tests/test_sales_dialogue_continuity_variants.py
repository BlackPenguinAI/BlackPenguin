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


def visit_frame(text):
    data=understanding(text,'appointment').model_dump(mode='json')
    data.update(visit={'action':'request','evidence':text,'timing':None},
        references=[{'id':'bad','kind':'appointment','expression':'/','evidence':text}])
    data['requests'][0]['reference_id']='bad'
    return Understanding.model_validate(data)

@pytest.mark.parametrize('owner',['alder-home','orion-home','maple-home'])
@pytest.mark.parametrize('text',['Can I visit the property?','Could we visit this house?','I want to visit that home.','Please arrange a visit to the property.'])
def test_new_visit_placeholder_retains_current_property_without_slot_consent(owner,text):
    u=visit_frame(text)
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id=owner),previous({}))
    assert fixed.references[0].kind=='property' and fixed.references[0].expression=='this property'
    assert fixed.visit.action=='request' and fixed.confidence==u.confidence
    assert notes and fixed.requests[0].topic.value=='appointment'

@pytest.mark.parametrize('name',['Alder Cottage','Orion Duplex','Maple Terrace'])
@pytest.mark.parametrize('prefix',['Can I visit ','I want to visit ','I mean an in-person visit to '])
def test_named_new_visit_placeholder_becomes_only_approved_named_subject(name,prefix):
    text=prefix+name+'?';u=visit_frame(text)
    fixed,notes=consistent(u,text,{'property_types':[{'property_type':name}]})
    assert fixed.references[0].kind=='property' and fixed.references[0].expression==name
    assert fixed.visit.action=='request' and fixed.confidence==u.confidence

@pytest.mark.parametrize('text',['16/11, 10am','Yes','Cancel my visit','My friend said can I visit the property?','Can I visit the other property?'])
def test_no_slot_confirmation_or_other_property_is_rebound(text):
    u=visit_frame(text)
    fixed,_=normalize(u,text,DialogueState(selected_property_type_id='home'),previous({}))
    assert fixed.references[0].kind=='appointment'

@pytest.mark.parametrize('text',['Can I see it?','Could we view that?','Can we see this please?'])
def test_conflicting_material_read_after_visit_invitation_asks_without_effects(text):
    u=understanding(text,'materials')
    fixed,notes=normalize(u,text,DialogueState(selected_property_type_id='home'),previous({'visit_invitation':True}))
    assert fixed.requires_clarification and 'in person' in fixed.clarification_question
    assert not fixed.requests and not fixed.references and fixed.visit is None
    assert fixed.confidence==u.confidence and notes[-1]['effect_authorization'] is False
    # A current material offer keeps its interpretation; it is not visit consent.
    assert normalize(u,text,DialogueState(selected_property_type_id='home'),previous({'material_offer':{'asset_ids':['file']}}))[0]==u
    assert normalize(u,text,DialogueState(selected_property_type_id='home'),previous({'visit_invitation':True},'failed'))[0]==u


def test_matching_visit_intent_after_invitation_can_bind_it_but_never_confirm():
    u=visit_frame('Can I see it?')
    fixed,_=normalize(u,'Can I see it?',DialogueState(selected_property_type_id='home'),previous({'visit_invitation':True}))
    assert not fixed.requires_clarification and fixed.references[0].kind=='property'
    assert fixed.visit.action=='request'

@pytest.mark.parametrize('text',['Can I visit this unit?','Please arrange a viewing of the unit.'])
def test_new_unit_visit_uses_current_unit_and_preserves_type(text):
    u=visit_frame(text)
    fixed,_=normalize(u,text,DialogueState(selected_property_type_id='home',selected_unit_id='unit-a'),previous({}))
    assert fixed.references[0].kind=='unit' and fixed.references[0].expression=='this unit'
    assert fixed.visit.action=='request'


def test_missing_subject_or_real_slot_reference_is_never_replaced():
    from app.modules.sales_agent.understanding_contract import Reference
    text='Can I visit the property?';u=visit_frame(text)
    assert normalize(u,text,DialogueState(),previous({}))[0].references[0].kind=='appointment'
    real=u.model_copy(update={'references':[Reference(id='bad',kind='appointment',expression='first appointment',evidence=text)]})
    assert normalize(real,text,DialogueState(selected_property_type_id='home'),previous({'appointment_offer':{'options':[]}}))[0].references[0].expression=='first appointment'
