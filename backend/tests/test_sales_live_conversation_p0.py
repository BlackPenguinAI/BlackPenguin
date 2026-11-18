"""Offline gates for evidence-bound live WhatsApp/SMS continuations.

No provider, credentials, SMS/WhatsApp sends or external appointments.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.modules.sales_agent.live_visit_continuity import classify
from app.modules.sales_agent.understanding_contract import Understanding, Topic
from app.modules.sales_agent.continuity_policy import confirmed_controls


def state(*, selected='property-1', restricted=False):
    constraints=[NS(topic=NS(value='appointment'))] if restricted else []
    return NS(selected_property_type_id=selected, constraints=constraints, property_constraints=[])


def offer():
    return {'appointment_offer': {'version':'test-only',
        'context':{'property_type_id':'property-1','property_type_name':'Madison'},
        'options':[{'starts_at':'2026-12-01T16:00:00+00:00'}],
        'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}}


def test_yes_accepts_only_current_visit_invitation_as_search_not_booking():
    assert classify('Yes',{'visit_invitation':True},state())=='accepted_visit_invitation'
    assert classify('Yes',{},state()) is None
    assert classify('Yes',{'control_confirmation':'human','visit_invitation':True},state()) is None
    assert classify('Yes',{'booking_confirmation':{'id':'p'},'visit_invitation':True},state()) is None
    assert classify('Yes',{'visit_invitation':True},state(restricted=True)) is None
    assert classify('Yes',{'visit_invitation':True},state(),action_holds={'appointment'}) is None
    assert classify('Yes',{'appointment_offer':offer()['appointment_offer']},state()) is None


def test_property_reaffirmation_preserves_visit_flow_without_selecting_a_slot():
    current=offer()
    assert classify('Madison',current,state())=='reaffirmed_offered_property'
    assert classify('MADISON!',current,state())=='reaffirmed_offered_property'
    assert classify('1',current,state()) is None
    assert classify('Yes',current,state()) is None
    assert classify('Cleveland',current,state()) is None
    assert classify('Madison',current,state(selected='other')) is None
    assert classify('Madison',current,state(restricted=True)) is None
    current['appointment_offer']['expires_at']='2020-01-01T00:00:00+00:00'
    assert classify('Madison',current,state()) is None


def test_transfer_label_without_explicit_evidence_is_not_escalation():
    msg='What happened?'
    u=Understanding.model_validate({
        'version':'sales-understanding/1.0',
        'requests':[{'id':'r1','topic':'human','polarity':'request','evidence':msg}],
        'all_of':['r1'],'alternatives':[],'constraints':[],
        'references':[],'preferences':[], 'requires_clarification':True,
        'clarification_question':'Would you like me to transfer this conversation to the Sales team?',
        'confidence':0.0})
    assert u.requests[0].topic is Topic.human
    fixed=confirmed_controls(u,msg,pause_reason=None)
    assert fixed.requests[0].topic is Topic.other
    assert fixed.clarification_question is None
    assert not fixed.requires_clarification
    assert fixed.confidence==0.0  # no artificial confidence uplift
    assert confirmed_controls(u,'I want a human',pause_reason='HUMAN_REQUESTED').requests[0].topic is Topic.human


def test_ungrounded_human_does_not_erase_independent_property_request():
    msg='What happened? Please tell me the price of Madison.'
    u=Understanding.model_validate({
        'version':'sales-understanding/1.0',
        'requests':[{'id':'r1','topic':'human','polarity':'request','evidence':'What happened?'},
                    {'id':'r2','topic':'pricing','polarity':'request','evidence':'the price of Madison'}],
        'all_of':['r1','r2'],'alternatives':[],'constraints':[],
        'references':[],'preferences':[], 'requires_clarification':True,
        'clarification_question':'Would you like a human?', 'confidence':0.0})
    fixed=confirmed_controls(u,msg)
    assert [r.topic for r in fixed.requests]==[Topic.other,Topic.pricing]
    assert [r.id for r in fixed.requests]==['r1','r2']


def test_human_confirmation_requires_real_backend_prompt(monkeypatch):
    from app.modules.sales_agent import human_contact
    conversation=NS(continuity_json={})
    monkeypatch.setattr(human_contact,'_state',lambda c:{'stage':'asked','inbound_id':'original-request'})
    from app.modules.sales_agent import first_booking
    monkeypatch.setattr(first_booking,'accepted_outbound',lambda *a,**kw:NS(id='delivered'))
    assert human_contact.stage(None,None,conversation,'Yes',
         {'human_contact_prompt_inbound_id':'original-request'})=='record'
    assert human_contact.stage(None,None,conversation,'Yes',
         {'control_confirmation':'human'}) is None
    assert human_contact.stage(None,None,conversation,'Yes',
         {'human_contact_prompt_inbound_id':'some-other-request'}) is None


def test_human_record_uses_protected_intervention_and_company_notification(monkeypatch):
    from app.modules.sales_agent import human_contact
    from app.modules.governance import services
    from app.modules.sales_agent import dialogue_store, first_booking
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.models import SalesFollowUpJob
    requested=[]
    scope=NS(company_id='company',project_id='project',conversation_id='conversation',lead_id='lead')
    conversation=NS(id='conversation',continuity_json={})
    lead=NS(id='lead')
    state=NS(tasks=[])
    outcome=NS(state=state,results=[])
    class Query:
        def filter_by(self,**kw):return self
        def filter(self,*args):return self
        def all(self):return []
    db=NS(query=lambda model:Query(),flush=lambda:None)
    monkeypatch.setattr(dialogue_store,'check_scope',lambda db,scope:lead if False else NS(id='conversation',lead_id='lead'))
    monkeypatch.setattr(continuity,'state',lambda c:{'epoch':1})
    monkeypatch.setattr(first_booking,'stop_cadence',lambda *a:None)
    monkeypatch.setattr(services,'record_platform_event',lambda *a,**kw:None)
    def create_case(db,**kw):
        requested.append(kw)
        conversation.is_paused=True
        lead.agent_status='human_control'
        return NS(id='case-1')
    monkeypatch.setattr(services,'create_intervention_case',create_case)
    message,meta=human_contact.apply(db,scope,conversation,lead,outcome,NS(id='inbound-1',content='Yes'), 'record')
    assert requested[0]['reason']=='HUMAN_REQUESTED'
    assert meta['control_outcome']=='handoff'
    assert meta['human_intervention_case_id']=='case-1'
    assert conversation.is_paused
    assert lead.agent_status=='human_control'
    assert 'paused' in message


def test_composer_timeout_omits_optional_followup_but_keeps_required_fact(monkeypatch):
    import asyncio
    from app.modules.sales_agent import commercial_composer as composer, turn_memory
    from app.modules.sales_agent.understanding_contract import DialogueState
    from app.modules.sales_crm.models import Lead
    from test_sales_active_integration import understanding
    monkeypatch.setattr(composer,'resolve',lambda *a:{'model':'openai/gpt-4o-mini','source':{},'selection':{}})
    monkeypatch.setattr(turn_memory,'build',lambda *a,**kw:{'appointments':{'active':{'count':0}}})
    monkeypatch.setattr(composer,'select_continuations',lambda **kw:[
        {'id':'optional_visit','text':'Would you like a visit?','metadata':{}},
        {'id':'none','text':'','metadata':{}}])
    async def timeout(*_):
        raise TimeoutError()
    result=asyncio.run(composer.compose(None,None,
        inbound=NS(id='synthetic',content='What is the listed price?'),
        outcome=NS(state=DialogueState(last_understanding=understanding('What is the listed price?')),
                   results=[],plan={}),
        draft=NS(text='Published listed price is 489,900 USD.'),
        commercial={'confirmed_project_facts':{},'property_types':[]},
        lead=Lead(meta_form_data={},lead_profile_data={}),
        metadata={},previous_meta={},holds=[],channel='whatsapp',infer=timeout))
    assert result.trace['status']=='safe_fallback'
    assert result.trace['attempts'][0]['error_code']=='TimeoutError'
    assert result.trace['selected_continuation']=='none'
    assert '489,900' in result.text
    assert 'Would you like a visit?' not in result.text


def test_visit_preview_is_only_an_interpretation_and_resets_stale_search(monkeypatch):
    from app.modules.sales_agent import live_visit_continuity as live_visit
    from app.modules.sales_agent import first_booking, dialogue_store
    from app.modules.sales_agent.understanding_contract import DialogueState
    sent=[]
    monkeypatch.setattr(first_booking,'accepted_outbound',
                        lambda db,conversation,key:NS(metadata_json={'visit_invitation':True}))
    def save(db,scope,**kw):
        sent.append(kw)
        return 7,kw['state']
    monkeypatch.setattr(dialogue_store,'save',save)
    state=DialogueState(selected_property_type_id='property-1',
                        booking_search={'date_from':'2026-11-01','timezone':'UTC'},
                        booking_proposal={'old':'stale'})
    result=live_visit.try_preview(None,NS(),NS(id='conversation'),NS(id='inbound',content='Yes'),
        state=state,previous_meta={'visit_invitation':True},expected_revision=6,
        event_key='active-understanding:inbound')
    assert result.status=='accepted'
    assert result.state.last_understanding.visit.action=='request'
    assert result.state.last_understanding.permits('appointment')
    assert result.state.booking_search=={}
    assert result.state.booking_proposal is None
    assert state.booking_search['date_from']=='2026-11-01'  # no mutation of caller
    assert sent[0]['metadata']['effect_authorization'] is False
    assert sent[0]['metadata']['decision']=='accepted_visit_invitation'


def test_previous_processing_error_gets_bounded_explanation_not_handoff():
    from app.modules.sales_agent.live_failure_continuity import explanation,FALLBACKS
    for last in FALLBACKS:
        answer=explanation('¿What happened?',last)
        assert answer and 'previous response' in answer
        assert 'transfer' not in answer.lower() and 'Sales team' not in answer
    assert explanation('What happened?','Welcome back. What would you like to know?') is None
    assert explanation('Do you want a human?',next(iter(FALLBACKS))) is None
