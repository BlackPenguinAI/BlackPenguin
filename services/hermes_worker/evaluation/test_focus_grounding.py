"""Negative and positive controls for the evidence-based detail evaluation."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from diagnostics import SafeTrace, clean_event
from focus_grounding import FocusGrounding, assert_fact_reply

SCOPE = SimpleNamespace(company_id='co',project_id='project',lead_id='lead',conversation_id='conversation')
MESSAGE = 'The second option. How many bathrooms does it have?'
CONTEXT = {
    'company':{'id':'co'}, 'project':{'id':'project'}, 'registered_contact':{'id':'lead'},
    'conversation_focus':{'project_id':'project','property_type_id':'oak','unit_id':None,'ambiguous':False},
    'focused_property':{'kind':'property_type','id':'oak','reference':'oak','display_name':'Oakwood','bathrooms':2},
    'available_property_types':[{'id':'van','property_type':'Van Buren','bathrooms':1},
                                {'id':'oak','property_type':'Oakwood','bathrooms':2}],
    'resolved_visible_choice':{'type':'property','status':'resolved','choice':{'unit_id':'oak'}},
}
EXECUTED = [{'tool':'get_unit_details','status':'executed','error_code':None}]


def prepare():
    proof = FocusGrounding()
    proof.expect(scope=SCOPE, message=MESSAGE, ref='oak', name='Oakwood', field='bathrooms', value=2, ordinal=True)
    return proof, SimpleNamespace(scope=deepcopy(SCOPE),message=MESSAGE,channel='sms',verified_context=deepcopy(CONTEXT))


@pytest.mark.parametrize('observations,expected', [([], 'verified_context'), (EXECUTED,'verified_context_and_tool')])
def test_verified_input_with_or_without_redundant_read(observations,expected):
    proof,request = prepare(); proof.observe(request)
    trace = SafeTrace()
    assert proof.finish(observations=observations,trace=trace) == expected
    assert trace.events == [{'event':'fact_grounding','field':'bathrooms','verified_context':True,
                            'details_tool_executed':bool(observations),'details_tool_rejected':False}]


@pytest.mark.parametrize('change', ['wrong_scope','wrong_inbound','wrong_channel','wrong_tenant',
    'wrong_project','wrong_lead','ambiguous','wrong_focus','wrong_reference','wrong_name',
    'missing_focus_value','different_focus_value','missing_catalog_row','duplicate_catalog_row',
    'different_catalog_value','wrong_choice','ambiguous_choice','boolean_value','no_invocation',
    'duplicate_invocation','rejected_read'])
def test_unproven_fact_never_passes_even_with_apparently_correct_reply(change):
    proof,request = prepare(); c=request.verified_context
    observations = deepcopy(EXECUTED)
    if change == 'wrong_scope': request.scope.lead_id='other'
    if change == 'wrong_inbound': request.message='Different buyer message'
    if change == 'wrong_channel': request.channel='whatsapp'
    if change == 'wrong_tenant': c['company']['id']='other'
    if change == 'wrong_project': c['project']['id']='other'
    if change == 'wrong_lead': c['registered_contact']['id']='other'
    if change == 'ambiguous': c['conversation_focus']['ambiguous']=True
    if change == 'wrong_focus': c['conversation_focus']['property_type_id']='van'
    if change == 'wrong_reference': c['focused_property']['reference']='van'
    if change == 'wrong_name': c['focused_property']['display_name']='Van Buren'
    if change == 'missing_focus_value': c['focused_property'].pop('bathrooms')
    if change == 'different_focus_value': c['focused_property']['bathrooms']=1
    if change == 'missing_catalog_row': c['available_property_types'].pop()
    if change == 'duplicate_catalog_row': c['available_property_types'].append(deepcopy(c['available_property_types'][-1]))
    if change == 'different_catalog_value': c['available_property_types'][-1]['bathrooms']=1
    if change == 'wrong_choice': c['resolved_visible_choice']['choice']['unit_id']='van'
    if change == 'ambiguous_choice': c['resolved_visible_choice']['status']='ambiguous'
    if change == 'boolean_value': c['focused_property']['bathrooms']=True
    if change == 'rejected_read': observations.append({'tool':'get_unit_details','status':'rejected','error_code':'PROPERTY_REFERENCE_CONFLICT'})
    if change != 'no_invocation': proof.observe(request)
    if change == 'duplicate_invocation': proof.observe(request)
    with pytest.raises(AssertionError): proof.finish(observations=observations,trace=SafeTrace())


@pytest.mark.parametrize('name,field,value,reply', [
    ('Van Buren','bathrooms',1,'Van Buren has one bathroom.'),
    ('Oakwood','bathrooms',2,'Oakwood has **2** bathrooms.'),
    ('Van Buren','bedrooms',3,'Van Buren is a three-bedroom house.'),
])
def test_correct_accepted_reply(name,field,value,reply):
    assert_fact_reply(reply,name=name,field=field,value=value)


@pytest.mark.parametrize('reply', ['Oakwood has 1 bathroom.', 'Van Buren has 2 bathrooms.',
    'Oakwood has 2 bathrooms and 3 bathrooms.', 'Oakwood is beautiful.',
    'Oakwood has 12 bathrooms.'])
def test_wrong_property_wrong_fact_or_no_fact_fails(reply):
    with pytest.raises(AssertionError): assert_fact_reply(reply,name='Oakwood',field='bathrooms',value=2)


def test_grounding_event_cannot_export_context():
    assert clean_event({'event':'fact_grounding','field':'SECRET','verified_context':{'secret':'KEY'},
                        'details_tool_executed':False,'raw':'KEY'}) == {
                        'event':'fact_grounding','field':'unknown_field','details_tool_executed':False}
