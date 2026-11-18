"""P3-B: day-first availability is read-only and does not weaken booking consent."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from app.modules.sales_agent import visit_day_funnel as funnel


def _offer():
    now = datetime.now(timezone.utc)
    days = [(now + timedelta(days=offset)).date().isoformat() for offset in (1, 3, 4)]
    return {'version': funnel.VERSION, 'days': funnel.day_labels(days),
            'property_type_id': 'cleveland', 'timezone': 'UTC',
            'expires_at': (now + timedelta(minutes=30)).isoformat()}


def test_day_choice_ordinals_refer_only_to_offered_dates():
    offer = _offer()
    for phrase in ('2', 'Second option', 'the second one', 'Option 2'):
        assert funnel.choose(phrase, offer, 'cleveland') == offer['days'][1]['date']
    assert funnel.choose('Saturday at 11 AM', offer, 'cleveland') is None
    assert funnel.choose('Second option and book now', offer, 'cleveland') is None
    assert funnel.choose('2', offer, 'madison') is None
    assert funnel.choose('4', offer, 'cleveland') is None
    assert funnel.choose('2', {**offer, 'expires_at': '2020-01-01T00:00:00+00:00'}, 'cleveland') is None


def test_day_choice_accepts_unique_printed_day_but_not_ambiguous_weekday():
    offer = _offer()
    for item in offer['days']:
        assert funnel.choose(item['label'], offer, 'cleveland') == item['date']
    duplicated = {**offer, 'days': funnel.day_labels([
        '2099-11-07', '2099-11-14', '2099-11-15'])}
    duplicated['expires_at'] = (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    assert funnel.choose('Saturday', duplicated, 'cleveland') is None


def test_invalid_day_offer_fails_closed_without_booking():
    offer = _offer()
    assert funnel.choose('2', {**offer, 'days': offer['days'][::-1]}, 'cleveland') is None
    assert funnel.choose('2', {**offer, 'days': [offer['days'][0]]*2}, 'cleveland') is None
    assert funnel.choose('2', {**offer, 'timezone': 'Unknown/Nowhere'}, 'cleveland') is None
    assert funnel.choose('2', {**offer, 'version': 'untrusted'}, 'cleveland') is None


def test_spread_real_slots_without_creating_new_candidates():
    slots = [{'start_at': i} for i in range(15)]
    result = funnel.spread_slots(slots)
    assert [v['start_at'] for v in result] == [0, 7, 14]
    assert funnel.spread_slots(slots[:2]) == slots[:2]
    assert funnel.spread_slots([]) == []


def test_day_offer_narrative_includes_approved_property():
    offer = _offer()
    text = funnel.message('Cleveland', offer['days'], 'America/Denver')
    assert 'Cleveland' in text and 'Denver local time' in text
    assert '\n2. ' + offer['days'][1]['label'] in text
    assert 'Which day works best' in text


def test_exact_day_continuation_previews_only_new_slot_search(monkeypatch):
    from app.modules.sales_agent import first_booking, dialogue_store
    from app.modules.sales_agent.understanding_contract import DialogueState
    offer = _offer()
    previous = NS(id='outbound-day-offer', metadata_json={'visit_day_offer': offer})
    monkeypatch.setattr(first_booking, 'accepted_outbound', lambda *a,**kw: previous)
    saved = []
    def save(db, scope, **kwargs):
        saved.append(kwargs)
        return 8, kwargs['state']
    monkeypatch.setattr(dialogue_store, 'save', save)
    old = DialogueState(selected_property_type_id='cleveland', booking_search={
        'property_type_id':'cleveland', 'timezone':'UTC', 'duration_minutes':45,
        'time_relation':'any', 'date_from':None, 'date_until':None})
    outcome = funnel.try_preview(NS(), NS(), NS(),
        NS(id='inbound-day', content='the second one'), state=old,
        previous_meta=previous.metadata_json, expected_revision=7,
        event_key='active-understanding:inbound-day')
    assert outcome and outcome.status == 'accepted'
    assert outcome.state.booking_search['date_from'] == offer['days'][1]['date']
    assert outcome.state.booking_search['date_until'] == offer['days'][1]['date']
    assert outcome.state.booking_search['day_offer_selection_message_id'] == 'inbound-day'
    assert outcome.state.booking_proposal is None
    assert outcome.state.last_understanding.visit.action == 'request'
    assert outcome.state.last_understanding.permits('appointment')
    assert saved[0]['metadata']['effect_authorization'] is False
    assert old.booking_search['date_from'] is None
    assert old.last_understanding is None


def test_day_scan_uses_distinct_days_and_exact_day_uses_spaced_slots(monkeypatch):
    from app.modules.sales_agent import first_booking
    from app.modules.sales_crm import scheduling
    first_booking.eligible_appointment_assignments
    monkeypatch.setattr(first_booking, 'eligible_appointment_assignments', lambda *a,**kw:[NS(user_id='u')])
    calls=[]
    zone=ZoneInfo('America/Denver')
    starts=[datetime(2026,11,21,9,0,tzinfo=zone)+timedelta(minutes=30*i) for i in range(15)]
    def available(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get('distinct_local_days_timezone'):
            return [{'start_at': d.astimezone(timezone.utc).replace(tzinfo=None)}
                    for d in [datetime(2026,11,i,9,0,tzinfo=zone) for i in (20,21,23)]]
        return [{'start_at': t.astimezone(timezone.utc).replace(tzinfo=None), 'eligible_sales_user_ids':['u']} for t in starts]
    monkeypatch.setattr(scheduling, 'available_slots', available)
    monkeypatch.setattr(first_booking, 'choose_user', lambda *a,**kw:'u')
    class Query:
        def filter_by(self,**kw):return self
        def first(self):return NS(id='u',first_name='Verified',last_name='Specialist')
    db=NS(query=lambda model: Query())
    scope=NS(project_id='project', company_id='company')
    prefs={'timezone':'America/Denver','date_from':'2026-11-18','date_until':'2026-11-25',
           'time_relation':'any','time_from':None,'time_until':None,'duration_minutes':45}
    now=datetime(2026,11,18,15,0)
    days=first_booking.search_slots(db,scope,prefs,now,days_only=True)
    assert days == ['2026-11-20','2026-11-21','2026-11-23']
    assert calls[-1]['limit']==3 and calls[-1]['distinct_local_days_timezone']=='America/Denver'
    prefs={**prefs,'date_from':'2026-11-21','date_until':'2026-11-21'}
    slots=first_booking.search_slots(db,scope,prefs,now)
    local=[datetime.fromisoformat(o['starts_at']).astimezone(zone).strftime('%H:%M') for o in slots]
    assert local == ['09:00','12:30','16:00']
    assert calls[-1]['limit']==32 and 'distinct_local_days_timezone' not in calls[-1]


def test_distinct_day_scan_skips_rest_of_day_after_verified_opening(monkeypatch):
    from app.modules.sales_crm import scheduling
    monkeypatch.setattr(scheduling, 'eligible_appointment_assignments',lambda db,project_id:[NS(user_id='u')])
    monkeypatch.setattr(scheduling, 'eligible_users_for_slot',lambda *a,**kw:['u'] if kw['starts_at'].hour==16 else [])
    class Query:
        def filter(self,*a,**kw):return self
        def first(self):return None
    db=NS(query=lambda model:Query())
    result = scheduling.available_slots(db,project_id='project',
        after=datetime(2026,11,18,15,0),days=5,limit=3,
        duration_minutes=45,distinct_local_days_timezone='America/Denver')
    dates=[s['start_at'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/Denver')).date().isoformat() for s in result]
    assert dates==['2026-11-18','2026-11-19','2026-11-20']


def test_scripted_buyers_select_day_from_outbound_text_not_hidden_offer():
    from tools.sales_ai.booking_pilot import next_message
    from tools.sales_ai.compact_battery import public_next
    reply = ('For Bay Residence, I found visit availability on these days (UTC local time):\n\n'
             '1. Thursday, November 19\n2. Saturday, November 21\n\n'
             'Which day works best for your visit to Bay Residence?')
    assert next_message(reply,[]) == ('1','select_day')
    assert public_next(reply,[],'Bay Residence',2) == ('1','select_day')
    assert public_next(reply,[],'Cleveland',2)[1] == 'clarify_visit'


import pytest


@pytest.mark.parametrize('available_days,expected_kind',[
    (['2026-11-20','2026-11-21','2026-11-23'],'visit_day_offer'),
    (['2026-11-21'],'appointment_offer'),
])
def test_first_booking_funnels_only_when_multiple_verified_days(
    monkeypatch, available_days, expected_kind
):
    from app.modules.sales_agent import first_booking, commercial_context
    from app.modules.sales_agent.understanding_contract import DialogueState, Task, Understanding
    text = 'I would like to visit Cleveland.'
    u = Understanding.model_validate(dict(
        version='sales-understanding/1.0',
        requests=[dict(id='r1',topic='appointment',polarity='request',evidence=text)],
        all_of=['r1'], alternatives=[], constraints=[], references=[], preferences=[],
        visit={'action':'request','evidence':text,'timing':None},
        requires_clarification=False,clarification_question=None,confidence=1.0))
    state = DialogueState(selected_property_type_id='cleveland',last_understanding=u,
        tasks=[Task(id='task',topic='appointment',status='pending',source_message_id='in')])
    outcome = NS(state=state,plan={
        'write_candidates_require_backend_authorization':['task'],
        'references':{}})
    scope = NS(company_id='company',project_id='project',lead_id='lead')
    project = NS(id='project',profile=None,timezone='America/Denver')
    location={'label':'Office','address':'100 Test Street'}
    prefs={'timezone':'America/Denver','date_from':None,'date_until':None,
           'time_relation':'any','time_from':None,'time_until':None,
           'duration_minutes':45,'source_evidence':{},'source':'test'}
    monkeypatch.setattr(first_booking,'normalize_timing',lambda *a,**kw:prefs)
    monkeypatch.setattr(first_booking,'active_meetings',lambda *a,**kw:[])
    monkeypatch.setattr(first_booking,'accepted_outbound',lambda *a,**kw:None)
    monkeypatch.setattr(first_booking,'resolve_visit_location',lambda *a,**kw:location)
    monkeypatch.setattr(first_booking,'context_snapshot',lambda *a,**kw:{
        'property_type_id':'cleveland','property_type_name':'Cleveland','location':location,
        'duration_minutes':45})
    monkeypatch.setattr(commercial_context,'build_commercial_context',lambda *a,**kw:{
        'property_types':[{'id':'cleveland','property_type':'Cleveland'}]})
    calls=[]
    def search(*a,**kw):
        calls.append(kw.get('days_only',False))
        if kw.get('days_only'):
            return available_days
        return [{'starts_at':'2026-11-21T16:00:00+00:00',
                 'sales_user_id':'seller','specialist_name':'Verified Specialist'}]
    monkeypatch.setattr(first_booking,'search_slots',search)
    reply,meta,actions=first_booking.handle(
        NS(),scope,NS(),NS(),project,outcome,NS(id='in',content=text))
    assert expected_kind in meta
    assert 'Cleveland' in reply
    assert not any(a.get('type')=='appointment_confirmed' for a in actions)
    assert state.booking_proposal is None
    if expected_kind=='visit_day_offer':
        assert calls == [True]
        assert len(meta['visit_day_offer']['days'])==3
        assert meta['visit_day_offer']['property_type_id']=='cleveland'
        assert 'Which day works best' in reply
    else:
        assert calls == [True,False]
        assert state.booking_search['date_from']=='2026-11-21'
        assert len(meta['appointment_offer']['options'])==1
