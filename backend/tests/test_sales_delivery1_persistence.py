"""Production-session boundaries, new-session reads, atomicity and temporal repair."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from sqlalchemy.orm import Session
from app.modules.sales_agent.understanding_contract import Understanding,response_schema,parse
from app.modules.sales_agent.understanding_repair import constrained_repair_schema,omit_declaration_questions
from app.modules.sales_agent.understanding_semantics import issues_for
from app.modules.sales_agent.evidence import EvidenceError
from app.modules.sales_agent.lead_profile import resolve
from app.modules.sales_crm.models import Lead,Meeting
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_active_integration import understanding


def declared(text):
    data=understanding(text,'other').model_dump()
    data['preferences']=[{'key':'budget','value':'900000 USD','evidence':'My budget is 900,000 USD','status':'declared'},
        {'key':'financing','value':'cash','evidence':'I can pay cash','status':'declared'}]
    return Understanding.model_validate(data)


def test_declarations_survive_composition_reauthorization_and_new_session(agent):
    agent.db.autoflush=False
    text='My budget is 900,000 USD. I can pay cash'
    _,run=agent.turn(text,declared(text))
    assert run.error_code is None
    with Session(bind=agent.db.get_bind(),autoflush=False) as reader:
        profile=resolve(reader.get(Lead,agent.lead.id))['current']
        assert profile['budget']['status']=='declared' and '900,000 USD' in profile['budget']['value']
        assert profile['financing']['status']=='declared' and 'cash' in profile['financing']['value']
    agent.turn('Thanks',understanding('Thanks','other'))
    with Session(bind=agent.db.get_bind(),autoflush=False) as reader:
        assert resolve(reader.get(Lead,agent.lead.id))['current']['budget']['status']=='declared'


def test_interruption_after_capture_rolls_back_flushed_profile(agent,monkeypatch):
    from app.modules.sales_agent import active_service,lead_profile
    agent.db.autoflush=False
    initial=deepcopy(agent.lead.lead_profile_data)
    original_capture=lead_profile.capture;original_current=active_service._current
    flag={'captured':False,'interrupted':False}
    def capture(*args,**kwargs):
        value=original_capture(*args,**kwargs);flag['captured']=True;return value
    def current(*args,**kwargs):
        if flag['captured']:
            flag['captured']=False;flag['interrupted']=True
            raise PermissionError('Synthetic interruption before commit')
        return original_current(*args,**kwargs)
    monkeypatch.setattr(lead_profile,'capture',capture)
    monkeypatch.setattr(active_service,'_current',current)
    text='My budget is 900,000 USD. I can pay cash'
    _,run=agent.turn(text,declared(text))
    assert flag['interrupted']
    agent.send.assert_not_awaited()
    with Session(bind=agent.db.get_bind(),autoflush=False) as reader:
        assert reader.get(Lead,agent.lead.id).lead_profile_data==initial
        assert reader.query(Meeting).count()==0


def test_repair_covers_nested_timing_and_retains_valid_current_timezone():
    current='Please use the project timezone and check viewing times.'
    data=understanding(current,'appointment').model_dump()
    data['visit']={'action':'request','evidence':current,'timing':{'date_from_evidence':'next seven days','timezone_evidence':'project timezone'}}
    import json
    raw=json.dumps(data)
    schema=constrained_repair_schema(response_schema(current),current,raw)
    fields=schema['$defs']['VisitTiming']['properties']
    date_branch=next(b for b in fields['date_from_evidence']['anyOf'] if b.get('type')=='string')
    zone_branch=next(b for b in fields['timezone_evidence']['anyOf'] if b.get('type')=='string')
    assert 'next seven days' not in date_branch['enum']
    assert 'project timezone' in zone_branch['enum']
    assert any(b.get('type')=='null' for b in fields['date_from_evidence']['anyOf'])
    with pytest.raises(EvidenceError):parse(raw,current)
    data['visit']['timing']['date_from_evidence']=None
    assert parse(json.dumps(data),current).visit.timing.timezone_evidence=='project timezone'


@pytest.mark.parametrize('phrase',['paying cash.','I can pay cash','I have cash available'])
def test_own_cash_declaration_is_not_a_financing_policy_question(phrase):
    value=understanding(phrase,'financing').model_dump()
    value['preferences']=[{'key':'financing','value':'cash','evidence':phrase,'status':'declared'}]
    frame=Understanding.model_validate(value)
    repaired,audit=omit_declaration_questions(frame,issues_for(frame,phrase))
    assert repaired.requests==[] and repaired.preferences==frame.preferences
    assert audit and not repaired.visit
    question='Do you accept cash?'
    frame=understanding(question,'financing')
    assert omit_declaration_questions(frame,issues_for(frame,question))[0]==frame
