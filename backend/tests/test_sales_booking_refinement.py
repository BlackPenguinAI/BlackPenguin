"""Observed booking-point regressions: semantic loss, exact options and formatting."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import pytest
from app.modules.sales_agent.first_booking import exact_public_selection,label,VERSION
from app.modules.sales_agent.service import _requested_period
from app.modules.sales_agent.response_policy import render_channel_text
from app.modules.sales_agent.understanding_semantics import issues_for
from app.modules.sales_agent.understanding_contract import Understanding
from test_sales_active_integration import understanding


def offered():
    return {'version':VERSION,'preferences':{'timezone':'America/New_York'},'options':[
        {'starts_at':'2026-11-12T15:00:00+00:00','specialist_name':'Synthetic Sales','sales_user_id':'private-user-id'},
        {'starts_at':'2026-11-12T15:30:00+00:00','specialist_name':'Synthetic Sales','sales_user_id':'private-user-id'}]}


def test_exact_selection_prepares_only_a_publicly_offered_option():
    offer=offered();text='I would like the first appointment: '+label(offer['options'][0],offer['preferences'])+'.'
    assert exact_public_selection(text,offer)=={'kind':'appointment','id':'2026-11-12T15:00:00+00:00'}
    alternate='The first time does not work for me. I would like the second appointment: '+label(offer['options'][1],offer['preferences'])+'.'
    assert exact_public_selection(alternate,offer)['id']=='2026-11-12T15:30:00+00:00'
    for invalid in ['My friend said '+text,'If '+text,'Do not book. '+text,'Yes','first appointment',text.replace('10:00','11:00'),text.replace('first appointment','second appointment')]:
        assert exact_public_selection(invalid,offer) is None
    assert exact_public_selection(text,{**offer,'version':'expired-format'}) is None


@pytest.mark.parametrize('words',['next seven days','next 7 days','next three days','next 10 days'])
def test_relative_visit_range_is_not_fourteen_day_default(words):
    now=datetime(2026,11,10,21)
    first,last=_requested_period(words,now=now,zone=ZoneInfo('America/New_York'))
    count={'next seven days':7,'next 7 days':7,'next three days':3,'next 10 days':10}[words]
    assert first.isoformat()=='2026-11-10' and last-first==timedelta(days=count-1)


def test_semantic_feedback_distinguishes_cash_and_visit_timing():
    text='I would like a visit, paying cash. Any time in the next seven days works.'
    u=understanding(text,'appointment','financing','delivery')
    data=u.model_dump();data['requests'][1]['evidence']='paying cash';data['requests'][2]['evidence']='next seven days'
    issues=issues_for(Understanding.model_validate(data),text)
    assert {i['type'] for i in issues}=={'payment_declaration_missing','declaration_as_question','payment_declaration_as_question','visit_timing_as_delivery'}
    data['requests']=data['requests'][:1];data['all_of']=[data['requests'][0]['id']]
    data['preferences']=[{'key':'financing','value':'cash','evidence':'paying cash','status':'declared'}]
    assert issues_for(Understanding.model_validate(data),text)==[]


def test_abbreviated_selection_requires_an_appointment_reference():
    text='I would like the first appointment'
    assert issues_for(understanding(text,'appointment'),text,appointment_offer=True)[0]['type']=='appointment_selection_reference_missing'
    assert issues_for(understanding(text,'appointment'),text,appointment_offer=False)==[]


def test_inventory_quantity_is_not_a_new_list_item():
    text='1. Bay Residence. Last confirmed quantity: 3. Synthetic property. Features: Private garden.'
    for channel in ['sms','whatsapp']:
        rendered=render_channel_text(text,channel)
        assert 'quantity: 3.' in rendered and '\n\n3.' not in rendered
    assert '\n\n2. Loft' in render_channel_text('Confirmed types: 1. Studio 2. Loft','sms')
