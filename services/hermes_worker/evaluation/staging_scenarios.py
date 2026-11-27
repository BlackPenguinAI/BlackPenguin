"""Outcome-based demo parity acceptance. Synthetic catalog only.

No model routing, tool monkeypatch or state replacement in these scenarios.
The same assertions are exercised with a separate offline double, and the
real lane calls the pinned SDK via the real private HTTP client.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo
from sdk_scenarios import first_input, next_input, state, tools_for, verify_material_and_replay
from focus_grounding import assert_fact_reply

VARIANTS = {
    'focus-media': (
        ('How many bathrooms does Oakwood have?', 'How many bedrooms does Van Buren have?', 'Can you send me the PDF?'),
        ('Tell me the number of bathrooms in Oakwood.', 'What about Van Buren? How many bedrooms does it have?', 'Please send me its brochure.'),
        ('What is the bathroom count in Oakwood?', 'Switch to Van Buren. Tell me the number of bedrooms.', 'Could you share the PDF?'),
    ),
    'ordinal': (
        ('Show me the available 3 bedroom houses under $350,000 as a numbered list.', 'The second option. How many bathrooms does it have?'),
        ('Find 3 bedroom homes below $350,000.', 'Option 2. How many bathrooms does it have?'),
        ('Which houses with 3 bedrooms are under $350,000?', 'The second property. How many bathrooms does it have?'),
    ),
    'temporary': (
        ('My maximum budget is $350,000. I need exactly 3 bedrooms.', 'Show me 4 bedroom houses under $400,000.'),
        ('My budget is up to $350,000. I want exactly 3 bedrooms.', 'Find 4 bedroom homes below $400,000 just for comparison.'),
        ('I can spend up to $350,000. I require exactly 3 bedrooms.', 'Which properties with 4 bedrooms are under $400,000?'),
    ),
    'no-match': (
        ('Show me 6 bedroom houses under $100,000.',),
        ('Find 6 bedroom properties below $100,000.',),
        ('Which houses with 6 bedrooms are under $100,000?',),
    ),
    'comparison': (
        ('Compare Van Buren and Oakwood. How many bathrooms does each have, and which has more?',),
        ('Between Oakwood and Van Buren, which has more bathrooms? Give the count for each.',),
        ('What is the bathroom difference between Van Buren and Oakwood? Include both counts.',),
    ),
    'visit': (
        ('What days are available to visit Van Buren? Please list the options.', 'Option 2', 'Option 2', 'Yes, I confirm the visit.'),
        ('I want to visit Van Buren. Which days are available?', 'The second option', 'The second option', 'I confirm this appointment.'),
        ('When can I tour Van Buren in the upcoming days?', '2', '2', 'Please book the visit.'),
    ),
}
CASES = [(family, i) for family, variants in VARIANTS.items() for i in range(len(variants))]
CASE_IDS = [f'{family}-{i+1}' for family, i in CASES]
CHECKPOINTS = frozenset({'catalog','first_focus','focus_switch','material','stop','search','ordinal','primary','temporary',
    'no_match','comparison','visit_days','visit_times','visit_recap','visit_confirm','visit_replay','complete'})


def seed_extra_home(lane):
    from app.modules.projects.models import ProjectPropertyType
    lane.db.add(ProjectPropertyType(id='cedar', project_id='project', name='Cedar Grove', review_status='confirmed',
        bedrooms=4, bathrooms=3, starting_price=375000, currency='USD', available_units=1,
        inventory_updated_at=datetime.now(timezone.utc).replace(tzinfo=None), sort_order=2))
    lane.db.commit()


def seed_visits(lane):
    from app.modules.projects.models import Project
    from app.modules.users.models import User, UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock, CalendarConnection
    db=lane.db
    assert db.query(CalendarConnection).count()==0, 'No external calendar connection allowed'
    db.get(Project,'project').address='123 Main Street'
    db.get(lane.Lead,'lead').email='buyer@example.invalid'
    db.add(User(id='advisor', company_id='co', first_name='Test', last_name='Advisor', email='advisor@example.invalid',
                hashed_password='test-only',role=UserRole.SALES,is_active=True)); db.flush()
    db.add(ProjectUserAssignment(id='assignment',project_id='project',user_id='advisor',responsibility='sales',
                                sales_enabled=True,accepts_appointments=True,is_active=True))
    zone=ZoneInfo('America/Lima'); now=datetime.now(zone)
    dates=[]
    for offset in (2,3):
        day=(now+timedelta(days=offset)).replace(hour=10,minute=0,second=0,microsecond=0)
        dates.append(day.date().isoformat())
        start=day.astimezone(timezone.utc).replace(tzinfo=None)
        db.add(SalesAvailabilityBlock(id=f'slot-{offset}',user_id='advisor',starts_at=start,
            ends_at=start+timedelta(hours=2),timezone='America/Lima'))
    db.commit()
    return dates


def fact(lane, ref, field, value):
    names={'van':'Van Buren','oak':'Oakwood'}
    assert state(lane)['conversation_focus']['property_type_id']==ref
    assert_fact_reply(lane.calls[-1],name=names[ref],field=field,value=value)


def no_business_effect(lane):
    from app.modules.sales_crm.models import Meeting
    from app.modules.projects.models import SalesAssetShare
    assert lane.db.query(Meeting).count()==0
    assert lane.db.query(SalesAssetShare).count()==0
    lane.db.commit()


def accepted_no_match(reply):
    plain=re.sub(r'[*_`]', '',reply.casefold())
    assert re.search(r'\b(?:no (?:verified |available |matching )?(?:matches|houses|homes|properties|options|results)|'
        r'(?:could not|couldn.t|cannot|can.t|did not|didn.t|unable to) (?:find|locate|verify)|'
        r'(?:do not|don.t|does not|doesn.t) have|none (?:of|match)|not (?:have|available)|'
        r'no .*?match)\b',plain), 'No-match result was not communicated'
    if any(x in plain for x in ('van buren','oakwood','cedar grove')):
        assert re.search(r'\b(?:alternative|instead|however|different|outside|exceed|higher|over budget|closest|adjust)\b',plain), 'Alternative not distinguished'


def comparison_facts(reply):
    plain=re.sub(r'[*_`]', '',reply.casefold())
    # Bind numbers to the named property, not to another name later in a
    # shared sentence. Permit lists and ordinary prose, not a fixed template.
    for name, expected in [('van buren',1),('oakwood',2)]:
        count = r'\b(\d+|one|two|three|four|five|six)\s*[- ]?\s*bathrooms?\b'
        between = r'(?:(?!van buren|oakwood)[^\n.;]){0,90}?'
        direct = re.findall(re.escape(name)+between+count,plain)
        # Only use reverse order with an explicit connector to the property.
        reverse = re.findall(count+r'\s+(?:in|at|for|at the|in the)\s+'+re.escape(name),plain)
        words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6}
        values=[words[x] if x in words else int(x) for x in direct+reverse]
        assert values and all(v==expected for v in values), 'Missing or conflicting property-specific comparison fact' 


def exercise(lane, family, variant, checkpoint):
    messages=VARIANTS[family][variant]
    checkpoint('catalog')
    if family=='focus-media':
        checkpoint('first_focus'); first_input(lane,messages[0]); fact(lane,'oak','bathrooms',2)
        checkpoint('focus_switch'); next_input(lane,messages[1]); fact(lane,'van','bedrooms',3)
        checkpoint('material'); mid,jid=next_input(lane,messages[2]); assert state(lane)['conversation_focus']['property_type_id']=='van'
        verify_material_and_replay(lane,mid,jid)
        checkpoint('stop'); before=len(lane.sdk_calls);next_input(lane,'STOP')
        assert len(lane.sdk_calls)==before and lane.db.get(lane.Lead,'lead').is_opt_out
    elif family=='ordinal':
        checkpoint('search'); mid=first_input(lane,messages[0]); assert 'search_properties' in tools_for(lane,mid)
        menu=state(lane)['last_presented_choice_set'];assert menu and menu['type']=='property'
        assert len(menu['options'])==2 and {o['unit_id'] for o in menu['options']}=={'van','oak'}
        selected=menu['options'][1]['unit_id']
        checkpoint('ordinal');next_input(lane,messages[1]);fact(lane,selected,'bathrooms',1 if selected=='van' else 2)
        no_business_effect(lane)
    elif family=='temporary':
        seed_extra_home(lane)
        checkpoint('primary');first_input(lane,messages[0]); prefs=deepcopy(state(lane)['search_preferences'])
        assert prefs['budget']['maximum_usd']==350000 and prefs['bedrooms']['mode']=='exact' and prefs['bedrooms']['preferred']==3
        assert prefs['revision']>0 and prefs['last_source_message_id']=='inbound'
        checkpoint('temporary');mid,_=next_input(lane,messages[1]); current=state(lane)
        assert current['search_preferences']==prefs
        search=current['active_search']; assert search['source_inbound_message_id']==mid and search['scope']=='temporary' and search['match_count']==1
        assert search['criteria']['max_price_usd']==400000
        c=search['criteria'];assert c.get('bedrooms')==4 or c.get('bedrooms_any')==[4] or (c.get('bedrooms_min')==c.get('bedrooms_max')==4)
        assert 'cedar grove' in lane.calls[-1].casefold()
        no_business_effect(lane)
    elif family=='no-match':
        checkpoint('no_match');mid=first_input(lane,messages[0]);current=state(lane); search=current['active_search']
        assert search['source_inbound_message_id']==mid and search['match_count']==0
        criteria=search['criteria'];assert criteria['max_price_usd']==100000
        assert criteria.get('bedrooms')==6 or criteria.get('bedrooms_any')==[6] or (criteria.get('bedrooms_min')==criteria.get('bedrooms_max')==6)
        assert not current.get('last_presented_choice_set')
        accepted_no_match(lane.calls[-1]);no_business_effect(lane)
    elif family=='comparison':
        checkpoint('comparison');first_input(lane,messages[0]);comparison_facts(lane.calls[-1])
        no_business_effect(lane)
    elif family=='visit':
        from app.modules.sales_crm.models import Meeting
        from app.modules.hermes_sales_core.bp_operation_models import HermesSalesOperation
        dates=seed_visits(lane)
        checkpoint('visit_days');first_input(lane,messages[0]);s=state(lane);menu=s['last_presented_choice_set']
        assert menu and menu['type']=='visit_day' and menu['unit_id']=='van'
        assert [o['date'] for o in menu['options']]==dates and lane.db.query(Meeting).count()==0;lane.db.commit()
        checkpoint('visit_times');next_input(lane,messages[1]);s=state(lane);menu=s['last_presented_choice_set']
        assert menu and menu['type']=='visit_time' and menu['unit_id']=='van' and menu['date']==dates[1]
        assert [o['start_time'] for o in menu['options']]==['10:00','11:00'] and lane.db.query(Meeting).count()==0;lane.db.commit()
        checkpoint('visit_recap');next_input(lane,messages[2]);recap=state(lane)['confirmation_request']
        assert recap['status']=='awaiting_confirmation' and recap['unit_id']=='van' and recap['date']==dates[1] and recap['start_time']=='11:00'
        assert lane.db.query(Meeting).count()==0;lane.db.commit()
        checkpoint('visit_confirm');mid,jid=next_input(lane,messages[3]);meeting=lane.db.query(Meeting).one()
        assert meeting.duration_minutes==60 and meeting.visit_property_type_id=='van'
        expected_time=datetime.fromisoformat(recap['starts_at_utc']).astimezone(timezone.utc).replace(tzinfo=None)
        assert meeting.meeting_time==expected_time and meeting.assigned_sales_user_id=='advisor'
        assert meeting.gcal_event_id is None, 'This lane never creates external events'
        from app.modules.sales_agent.booking_models import SalesBookingOperation
        booking=lane.db.query(SalesBookingOperation).one();assert booking.meeting_id==meeting.id and booking.calendar_status=='pending'
        op=lane.db.query(HermesSalesOperation).filter_by(inbound_message_id=mid).one();assert op.status=='completed'
        assert 'van buren' in lane.calls[-1].casefold() and 'confirm' in lane.calls[-1].casefold()
        checkpoint('visit_replay');counts=(len(lane.calls),len(lane.sdk_calls))
        lane.db.get(lane.Job,jid).status='processing';lane.db.commit()
        from sdk_scenarios import run_claimed
        run_claimed(lane,jid)
        assert lane.db.query(Meeting).count()==1 and counts==(len(lane.calls),len(lane.sdk_calls))
    else:raise AssertionError('Unknown scenario')
    checkpoint('complete')
