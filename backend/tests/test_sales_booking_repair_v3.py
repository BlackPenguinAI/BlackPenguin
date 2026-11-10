"""Regressions from actual booking-point-2 provider output."""
import json
from datetime import datetime
from types import SimpleNamespace
import pytest
from app.modules.sales_agent.first_booking import normalize_timing
from app.modules.sales_agent.understanding_contract import response_schema,parse,Understanding
from app.modules.sales_agent.understanding_repair import constrained_repair_schema,evidence_choices
from app.modules.sales_agent.evidence import EvidenceError
from tools.sales_ai.booking_pilot import unavailable_message
from test_sales_active_integration import understanding


@pytest.mark.parametrize('phrase',["project timezone","the project's time zone","property timezone","this property time zone","the project’s timezone","project local time"])
def test_project_zone_reference_uses_published_zone_even_after_other_preference(phrase):
    text='I would like a visit in the '+phrase
    value=understanding(text,'appointment').model_dump()
    value['visit']={'action':'request','evidence':text,'timing':{'timezone_evidence':phrase}}
    u=Understanding.model_validate(value)
    prefs=normalize_timing(u,text,SimpleNamespace(timezone='America/New_York'),datetime(2026,11,10,21),{'timezone':'America/Chicago'})
    assert prefs['timezone']=='America/New_York'


def test_explicit_iana_zone_and_invalid_zone_keep_their_contract():
    text='Please use America/Lima';value=understanding(text,'appointment').model_dump()
    value['visit']={'action':'request','evidence':text,'timing':{'timezone_evidence':'America/Lima'}}
    u=Understanding.model_validate(value)
    assert normalize_timing(u,text,SimpleNamespace(timezone='America/New_York'),datetime(2026,11,10),{})['timezone']=='America/Lima'
    value['visit']['timing']['timezone_evidence']='Unknown/Zone'
    with pytest.raises(ValueError):normalize_timing(Understanding.model_validate(value),text,SimpleNamespace(timezone='UTC'),datetime(2026,11,10),{})


def test_repair_schema_constrains_quotes_without_weakening_parser():
    text='I am interested in Bay Residence and would like to book an in-person visit. My budget is 900,000 USD, paying cash.'
    schema=response_schema(text);repaired=constrained_repair_schema(schema,text)
    for name in ('Request','Preference'):
        assert 'enum' not in schema['$defs'][name]['properties']['evidence']
        choices=repaired['$defs'][name]['properties']['evidence']['enum']
        assert choices and all(q in text for q in choices)
        assert 'I would like to book an in-person visit.' not in choices
    data=understanding(text,'appointment').model_dump()
    data['requests'][0]['evidence']='I would like to book an in-person visit.'
    with pytest.raises(EvidenceError):parse(json.dumps(data),text)
    assert evidence_choices(text,'not JSON')==evidence_choices(text)


@pytest.mark.parametrize('reply',[
    'Would you like me to connect you with the sales team?',
    'Please specify a valid IANA timezone, such as America/Chicago.',
    'Which property do you want to visit?'])
def test_buyer_does_not_invent_unavailability(reply):
    text,action=unavailable_message(reply)
    assert action=='clarify_visit_request' and 'keep an eye out' not in text


def test_buyer_acknowledges_real_unavailability_and_rejects_unexpected_offer():
    assert unavailable_message('I could not find a verified time matching those preferences.')[1]=='acknowledge_unavailable'
    assert unavailable_message('Verified visit options:\n1. Thursday at 10:00 AM')==(None,'unexpected_visit_offer')
