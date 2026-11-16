from types import SimpleNamespace as N
import pytest
from app.modules.sales_agent.material_continuity import choices

def context():
    state=N(last_understanding=N(requests=[N(topic=N(value='materials'),polarity='request')],courtesy=None,empathy=None),selected_property_type_id='home',selected_unit_id=None,booking_search=None,booking_proposal=None,constraints=[],property_constraints=[],preferences=[N(key='bedrooms',value='3')])
    return N(state=state),{'property_types':[{'id':'home','property_type':'Juniper Home'}]},{'material_bindings':[{'share_id':'issued'}]},{}

def test_material_continuity_keeps_owner_preference_and_optional_silence():
    o,c,m,p=context();result=choices(o,c,m,p,set(),False)
    assert [x['id'] for x in result]==['material_interest','material_visit','material_review']
    assert '3 bedrooms' in result[0]['text'] and 'Juniper Home' in result[0]['text']
    assert result[-1]['text']=='' and all(x['text'].count('?')<=1 for x in result)
    assert all('book' not in x['metadata'] for x in result)

@pytest.mark.parametrize('reason',['booked','hold','decline','scoped_decline','pending_visit','prior_invite','previous_material','unknown_owner'])
def test_material_does_not_repeat_or_pressure(reason):
    o,c,m,p=context();holds=set();booked=False
    if reason=='booked':booked=True
    if reason=='hold':holds={'appointment'}
    if reason=='decline':o.state.constraints=[N(topic=N(value='appointment'))]
    if reason=='scoped_decline':o.state.property_constraints=[N(topic=N(value='appointment'),binding_status='resolved',property_id='home')]
    if reason=='pending_visit':o.state.booking_search={'pending':True}
    if reason=='prior_invite':p['visit_invitation']=True
    if reason=='previous_material':p['material_continuity']={'decision':'explore_current_property'}
    if reason=='unknown_owner':c['property_types']=[]
    assert [x['id'] for x in choices(o,c,m,p,holds,booked)]==['material_review']

@pytest.mark.parametrize('topic',['financing','appointment','property_details'])
def test_independent_questions_keep_their_own_continuation(topic):
    o,c,m,p=context();o.state.last_understanding.requests.append(N(topic=N(value=topic),polarity='request'))
    assert choices(o,c,m,p,set(),False) is None

def test_no_continuation_claim_before_delivery():
    o,c,m,p=context();assert choices(o,c,{},p,set(),False) is None
