"""Current request priority and bounded short visit requests, offline."""
from types import SimpleNamespace
import pytest
from test_sales_active_integration import understanding
from app.modules.sales_agent.interpretation_consistency import normalize
from app.modules.sales_agent.understanding_contract import DialogueState
from app.modules.sales_agent.planning_reply import continuation

@pytest.mark.parametrize('text',['Visit?','Viewing?','A viewing?','Can I see it?','Can we visit?'])
def test_short_visit_is_executable_search_without_confirmation(text):
    u=understanding(text).model_copy(update={'visit':__import__('app.modules.sales_agent.understanding_contract',fromlist=['VisitDirective']).VisitDirective(action='request',evidence=text)})
    fixed,notes=normalize(u,text,{'property_types':[]})
    assert fixed.permits('appointment') and fixed.visit.action=='request'
    assert fixed.confidence==u.confidence

@pytest.mark.parametrize('text',['No visit','My friend said Visit?','If I visit?','Cancel my visit','Do I have a visit?'])
def test_ambiguous_or_existing_visit_never_becomes_search(text):
    u=understanding(text)
    fixed,notes=normalize(u,text,{'property_types':[]})
    assert not fixed.permits('appointment')

@pytest.mark.parametrize('text,topic',[('Hi','other'),('Show me blueprints','materials'),('3 bedrooms?','catalog')])
def test_pending_appointment_cannot_override_current_request(text,topic):
    state=DialogueState(last_understanding=understanding(text,topic))
    outcome=SimpleNamespace(state=state,plan={'pending_topics':['appointment'],'questions':[]},stop_reason='complete')
    assert continuation(outcome,set())==('',{})

@pytest.mark.parametrize('text',['A viewing?','Viewing?','Blueprints?','Show me blueprints'])
def test_short_sales_vocabulary_is_english_without_granting_actions(text):
    from app.modules.sales_agent.language_policy import detect
    assert not detect(text).needs_reentry

@pytest.mark.parametrize('topic',['materials','property_details'])
def test_see_it_without_model_visit_interpretation_is_not_visit_consent(topic):
    text='Can I see it?'
    u=understanding(text,topic)
    fixed,notes=normalize(u,text,{'property_types':[]})
    assert not fixed.permits('appointment') and fixed.visit is None

@pytest.mark.parametrize('old,current',[('old-home','new-home'),('home','home')])
def test_legacy_search_is_reconciled_without_reselection(old,current):
    from app.modules.sales_agent.turn_planner import reconcile_subject
    from app.modules.sales_agent.understanding_contract import Task
    state=DialogueState(selected_property_type_id=current,booking_search={'property_type_id':old},
        tasks=[Task(id='old',topic='appointment',status='awaiting_user',property_id=old)])
    reconcile_subject(state,(current,None))
    if old!=current:
        assert not state.booking_search and state.tasks[0].status=='cancelled'
    else:
        assert state.booking_search and state.tasks[0].status=='awaiting_user'
