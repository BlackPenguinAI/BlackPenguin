"""Run 5 regression: appointment text cannot replace saved financial declarations."""
from copy import deepcopy
import pytest
from sqlalchemy.orm import Session
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_active_integration import understanding
from test_sales_delivery1_persistence import declared
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.understanding_repair import omit_unrelated_financial_preferences
from app.modules.sales_agent.understanding_semantics import issues_for
from app.modules.sales_agent.lead_profile import resolve
from app.modules.sales_crm.models import Lead


def contaminated(text):
    data=understanding(text,'appointment').model_dump()
    data['preferences']=[{'key':key,'value':value,'evidence':text,'status':'declared'}
        for key,value in [('budget','900000 USD'),('financing','cash')]]
    return Understanding.model_validate(data)


@pytest.mark.parametrize('text',[
    'I would like the first appointment: 2026-11-12 at 10:00 AM (America/New_York, UTC-0500); Synthetic all.',
    'The first time does not work for me. I would like the second appointment: Thursday at 10:30 AM.',
    'Please confirm my visit for Thursday.',
    'I prefer the afternoon viewing.',
])
def test_unrelated_current_quote_is_omitted_without_changing_appointment(text):
    frame=contaminated(text)
    assert {i['type'] for i in issues_for(frame,text)}=={'financial_preference_unrelated_evidence'}
    result,audit=omit_unrelated_financial_preferences(frame)
    assert result.preferences==[] and result.requests==frame.requests
    assert len(audit)==2 and issues_for(result,text)==[]


@pytest.mark.parametrize('text',[
    'I would like the first appointment. My budget is now 850,000 USD. I will use financing.',
    'I confirm the visit. My budget is 900000 USD and I can pay cash.',
])
def test_mixed_message_keeps_explicit_financial_changes(text):
    frame=contaminated(text)
    assert omit_unrelated_financial_preferences(frame)==(frame,[])


def test_profile_survives_selection_confirmation_and_accepts_real_correction(agent):
    agent.db.autoflush=False
    text='My budget is 900,000 USD. I can pay cash'
    agent.turn(text,declared(text))
    initial=deepcopy(resolve(agent.lead)['current'])
    selection='I would like the first appointment: Thursday at 10:00 AM.'
    agent.turn(selection,contaminated(selection))
    agent.turn('Yes',understanding('Yes','other'))
    with Session(bind=agent.db.get_bind(),autoflush=False) as reader:
        current=resolve(reader.get(Lead,agent.lead.id))['current']
        for field in ('budget','financing'):assert current[field]==initial[field]
    correction='My budget is 850,000 USD. I need financing'
    data=understanding(correction,'other').model_dump()
    data['preferences']=[{'key':'budget','value':'850000 USD','evidence':'My budget is 850,000 USD','status':'declared'},
        {'key':'financing','value':'financing','evidence':'I need financing','status':'declared'}]
    agent.turn(correction,Understanding.model_validate(data))
    with Session(bind=agent.db.get_bind(),autoflush=False) as reader:
        current=resolve(reader.get(Lead,agent.lead.id))['current']
        assert current['budget']['value']=='My budget is 850,000 USD'
        assert current['financing']['value']=='I need financing'
        for field in ('budget','financing'):assert current[field]['supersedes']==initial[field]['id']


@pytest.mark.parametrize('text',['Yes','Yes please.','Go ahead','Confirmed'])
def test_short_financial_answers_are_only_removed_in_booking_confirmation_context(text):
    frame=contaminated(text)
    assert omit_unrelated_financial_preferences(frame)==(frame,[])
    result,audit=omit_unrelated_financial_preferences(frame,appointment_confirmation=True)
    assert result.preferences==[] and len(audit)==2
    assert result.requests==frame.requests
