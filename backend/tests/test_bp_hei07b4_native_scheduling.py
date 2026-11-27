"""Regression for Cedar's 2026-11-27 incident: provider is a projection only."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.modules.sales_crm import scheduling as s
from app.modules.hermes_sales_core.live_domain_parity import contextual_bedrooms
from app.modules.hermes_sales_core.material_continuity import (
    MATERIALS, composition, render_delivery, standalone_question,
)

ZONE = ZoneInfo('America/Denver')

def utc(day, hour):
    return datetime(2026, 12, day, hour, tzinfo=ZONE).astimezone(timezone.utc).replace(tzinfo=None)


class MeetingQuery:
    def __init__(self, rows):
        self.rows = rows
    def filter(self, *expressions):
        # SQLAlchemy applies the same predicate in production. The fixture
        # supplies rows already filtered by salesperson/status/time.
        return self
    def all(self):
        return self.rows


@pytest.fixture
def schedule(monkeypatch):
    rows = {'sales': [], 'admin': []}
    blocks = {'sales': [SimpleNamespace(starts_at=utc(d,9),ends_at=utc(d,17)) for d in (2,4,5)],
              'admin': [SimpleNamespace(starts_at=utc(d,9),ends_at=utc(d,17)) for d in (4,5)]}
    assignments = [SimpleNamespace(user_id=k) for k in rows]
    monkeypatch.setattr(s, 'eligible_appointment_assignments', lambda db, pid: assignments if pid=='cedar' else [])
    monkeypatch.setattr(s, 'availability_blocks_for_user', lambda db, *,user_id,starts_at,ends_at: blocks[user_id])
    monkeypatch.setattr(s, 'availability_for_user', lambda db, uid: [])
    def forbidden(*args, **kwargs):
        pytest.fail('Google Calendar must not be queried while calculating availability')
    monkeypatch.setattr(s, 'calendar_busy_ranges', forbidden)
    monkeypatch.setattr(s, 'is_calendar_free', forbidden)
    monkeypatch.setattr(s, 'calendar_connections_for_user', forbidden)
    original = s._is_free
    # Feed only rows of the requested advisor to the actual _is_free function.
    def free(db, *,user_id,starts_at,ends_at,**kwargs):
        class DB:
            def query(self, model):
                assert model is s.Meeting, 'Availability must not load CalendarConnection'
                return MeetingQuery([r for r in rows[user_id] if r.meeting_time < ends_at])
        return original(DB(),user_id=user_id,starts_at=starts_at,ends_at=ends_at,**kwargs)
    monkeypatch.setattr(s, '_is_free', free)
    return rows


def test_cedar_wednesday_has_eight_hours_without_provider(schedule):
    slots=s.available_slots(None,project_id='cedar',after=utc(2,0),duration_minutes=60,days=1,limit=30,
        slot_predicate=lambda start,end: start.minute==0,include_sales_user_ids=True)
    assert [r['start_at'] for r in slots]==[utc(2,h) for h in range(9,17)]
    assert all(r['eligible_sales_user_ids']==['sales'] for r in slots)


def test_week_discovery_uses_working_blocks(schedule):
    slots=s.available_slots(None,project_id='cedar',after=utc(1,0),duration_minutes=60,days=6,limit=20,
        distinct_local_days_timezone='America/Denver',slot_predicate=lambda start,end: start.minute==0)
    assert [r['start_at'] for r in slots]==[utc(d,9) for d in (2,4,5)]
    assert [r['eligible_sales_users'] for r in slots]==[1,2,2]


def test_exact_slot_revalidation_respects_other_project_meeting(schedule):
    starts=utc(4,10)
    schedule['sales'].append(SimpleNamespace(id='other-project',meeting_time=starts,duration_minutes=60))
    assert s.eligible_users_for_slot(None,project_id='cedar',starts_at=starts,duration_minutes=60)==['admin']
    schedule['admin'].append(SimpleNamespace(id='another',meeting_time=starts,duration_minutes=60))
    assert not s.eligible_users_for_slot(None,project_id='cedar',starts_at=starts,duration_minutes=60)


def test_reschedule_excludes_only_its_own_meeting(schedule):
    starts=utc(4,10)
    own=SimpleNamespace(id='own',meeting_time=starts,duration_minutes=60)
    schedule['sales'].append(own)
    assert s.eligible_users_for_slot(None,project_id='cedar',starts_at=starts,duration_minutes=60,
        excluded_meeting=own,allowed_sales_user_ids={'sales'})==['sales']
    schedule['sales'].append(SimpleNamespace(id='other',meeting_time=starts,duration_minutes=60))
    assert not s.eligible_users_for_slot(None,project_id='cedar',starts_at=starts,duration_minutes=60,
        excluded_meeting=own,allowed_sales_user_ids={'sales'})


def test_empty_or_foreign_project_is_not_provider_failure(schedule):
    for pid, day in [('cedar',3),('foreign',2)]:
        assert s.available_slots(None,project_id=pid,after=utc(day,0),duration_minutes=60,days=1)==[]


def test_no_slot_extends_past_working_block(schedule):
    assert not s.eligible_users_for_slot(None,project_id='cedar',starts_at=utc(2,17)-timedelta(minutes=30),duration_minutes=60)


def test_explicit_additional_busy_constraints_are_backward_compatible(schedule):
    start=utc(2,9)
    assert not s.eligible_users_for_slot(None,project_id='cedar',starts_at=start,duration_minutes=60,
        external_busy_by_user={'sales':[(start,start+timedelta(hours=1))]})


@pytest.fixture
def prior():
    return {'active_search':{'criteria':{'bedrooms':2},'match_count':0},
            'search_preferences':{'bedrooms':{'mode':'preferred','preferred':2}}}


@pytest.mark.parametrize('reply', [
    'Would you like to look for properties with more bedrooms or different criteria?',
    'Would a larger home suit you?',
    'Would you like to explore listings with a different number of bedrooms?',
    'Would you consider 3-bedroom houses?',
])
def test_explicit_acceptance_not_tied_to_assistant_phrase(prior,reply):
    assert contextual_bedrooms('Yes, 3 bedrooms it’s ok',prior,reply)=={'bedrooms':{'mode':'preferred','preferred':3}}


@pytest.mark.parametrize('message,reply', [
    ('Show me 3-bedroom houses','Would a larger home suit you?'),
    ('Yes','Would a larger home suit you?'),
    ('Yes, 3 bedrooms it’s ok','Would you consider 4-bedroom houses?'),
    ('Yes, 3 bedrooms it’s ok',None),
])
def test_no_invented_or_temporary_preference(prior,message,reply):
    assert not contextual_bedrooms(message,prior,reply)


def test_no_match_from_unrelated_search_not_accepted(prior):
    prior['active_search']['criteria']={'max_price_usd':300000}
    assert not contextual_bedrooms('Yes, 3 bedrooms it’s ok',prior,'Would a larger home suit you?')


def test_no_match_does_not_relax_hard_bedroom_constraint(prior):
    prior['search_preferences']['bedrooms']['mode']='exact'
    assert not contextual_bedrooms('Yes, 3 bedrooms it’s ok',prior,'Would a larger home suit you?')


@pytest.mark.parametrize('question',['Would you like that?','Would you like to see it?','Can I send them?'])
def test_dangling_question_not_delivered(question):
    assert standalone_question(question) is None
    assert render_delivery('Approved gallery',{'question':question})=='Approved gallery'


def test_complete_native_template_keeps_commercial_continuation():
    reply=f'Here is the Cleveland gallery.\n{MATERIALS}\nWould you like to see the brochure?'
    assert composition(reply)==reply
    assert render_delivery('Approved gallery',{'template':reply})==reply.replace(MATERIALS,'Approved gallery')
