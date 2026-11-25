"""P04 Hermes operational drafts. No providers or live DB are contacted."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.modules.hermes_sales_core.bp_context import BPSnapshot
from app.modules.hermes_sales_core.bp_operational_port import BPOperationalDraftPort, P04_TOOL_NAMES
from app.modules.hermes_sales_core.bp_operation_receipts import booking_fingerprint, recap_visible
from app.modules.hermes_sales_core.bp_operation_receipts import visible_menu
from app.modules.hermes_sales_core.contracts import TurnScope
from app.modules.hermes_sales_core.choice_state import record_delivered_menu
from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
from app.modules.hermes_sales_core.config import HermesSettings

S = TurnScope('c-1','p-1','conv-1','lead-1')
NOW = datetime(2026, 11, 25, 15, 00, tzinfo=timezone.utc)
STARTS = [datetime(2026,11,27,h,tzinfo=timezone.utc) for h in (15,16,17)]


def snapshot():
    return BPSnapshot(
        scope=S,channel='simulation',company={'id':'c-1'},
        project={'id':'p-1','name':'Demo Project','timezone':'America/Lima'},
        lead={'id':'lead-1','full_name':'Demo Lead'},
        commercial={'inventory_source':'individual_units',
                    'inventory':[{'id':'u-1','unit_code':'H-201','property_type':'House',
                                  'price':180000,'currency':'USD','bedrooms':2,'bathrooms':2,
                                  'area':115,'status':'available','inventory_updated_at':'2026-11-25T10:00:00Z'}],
                    'available_assets':[{'asset_id':'asset-1','name':'Floor Plan',
                                         'asset_type':'floor_plan','content_tags':['floor_plan']}]},
    )


def fake_availability(**kwargs):
    assert kwargs['project_id']=='p-1'
    assert kwargs['duration_minutes']==60
    return [{'start_at':v} for v in STARTS]


def make_port(message='Show me available slots on 2026-11-27', state=None, **kwargs):
    state = deepcopy(state) if state is not None else {'conversation_focus': {'project_id':'p-1', 'unit_id':None},'visit_draft':{},'last_slot_search':None,'confirmation_request':None,'offered_assets':{},'property_interests':[]}
    state['conversation_focus']['unit_id']='H-201'
    return BPOperationalDraftPort(None,snapshot(),state=state,buyer_message=message,
                                  inbound_message_id=kwargs.pop('inbound','inbound-1'),
                                  now=kwargs.pop('now',NOW),availability_search=fake_availability,**kwargs)


def slot_offer():
    port=make_port()
    result=port.invoke('get_available_visit_slots',{'date_str':'2026-11-27'},S)
    return port, result


def published_offer():
    port,result=slot_offer()
    port.state['last_slot_search']['source_reply_message_id']='outbound-1'
    port.state['last_presented_choice_set']=record_delivered_menu(
        port.state,menu=port.menus[-1],outbound_message_id='outbound-1')
    return port.state,result


def fake_meeting():
    return SimpleNamespace(
        id='meeting-1',lead_id='lead-1',project_id='p-1',is_demo=True,
        assigned_sales_user_id='advisor-1',meeting_time=datetime(2026,11,28,15),duration_minutes=60,
        status=SimpleNamespace(value='confirmed'),visit_unit_id='u-1',visit_property_type_id=None,
        visit_address='123 Approved Street',visit_context={'timezone':'America/Lima'})


def test_new_slot_offer_is_read_only_and_unpublished():
    port,res=slot_offer()
    assert res['ok'] is True and res['booking_confirmed'] is False
    assert [s['start_time'] for s in res['available_slots']]==['10:00','11:00','12:00']
    assert port.state['last_slot_search']['source_reply_message_id'] is None
    assert port.state['confirmation_request'] is None
    assert port.menus[-1]['type']=='visit_time'


def test_slots_absent_are_successful_empty_discovery():
    port=make_port()
    # alternate: replace search on existing port
    port._availability_search=lambda **kw:[]
    res=port.invoke('get_available_visit_slots',{'date_str':'2026-11-27'},S)
    assert res['ok'] and res['available_slots']==[]
    assert not port.menus

@pytest.mark.parametrize('date_value', ['2026-11-02','2027-03-12','garbled Saturday next galaxy'])
def test_invalid_dates_fail_closed(date_value):
    port=make_port()
    res=port.invoke('get_available_visit_slots',{'date_str':date_value},S)
    assert res['error_code'] in {'DATE_OUT_OF_RANGE','UNSUPPORTED_PERIOD'}


def test_broad_days_do_not_imply_specific_times():
    port=make_port('Which days are available this week?')
    r=port.invoke('get_available_visit_slots',{'date_str':'this week'},S)
    assert r['available_dates']==[{'date':'2026-11-27'}]
    assert 'available_slots' not in r


def test_next_week_excludes_current_week_slots():
    port=make_port('Which days next week?')
    result=port.invoke('get_available_visit_slots',{'date_str':'next week'},S)
    assert result['ok'] and result['available_dates']==[]


def test_other_company_scope_rejected_before_query():
    port=make_port()
    with pytest.raises(PermissionError):
        port.invoke('get_available_visit_slots',{},TurnScope('c-2','p-1','conv-1','lead-1'))


def test_new_focus_outranks_old_visit_draft():
    port=make_port('What visits are available for H-202?')
    port.snapshot.commercial['inventory'].append({
        'id':'u-2','unit_code':'H-202','property_type':'House','price':190000,
        'currency':'USD','bedrooms':3,'bathrooms':2,'area':120,'status':'available',
        'inventory_updated_at':'2026-11-25T10:00:00Z',
    })
    port.state['visit_draft']={'unit_id':'H-201','status':'hour_needed'}
    result=port.invoke('get_available_visit_slots',{'date_str':'2026-11-27'},S)
    assert result['ok'] and result['unit_id']=='H-202'
    assert port.state['visit_draft']['unit_id']=='H-202'


def test_unpublished_offer_cannot_select_time():
    port,res=slot_offer()
    selection=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                            'date_str':'2026-11-27','start_time':'11:00'},S)
    assert selection['error_code']=='DELIVERED_OFFER_REQUIRED'


def test_published_second_option_is_not_the_first():
    state,res=published_offer()
    port=make_port('option 2',state,inbound='inbound-2')
    selected=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                          'date_str':'2026-11-27','start_time':'11:00'},S)
    assert selected['ok'] is True
    assert port.state['visit_draft']['start_time']=='11:00'
    assert port.state['confirmation_request']['status']=='recap_required'
    assert port.state['confirmation_request']['selected_inbound_message_id']=='inbound-2'


def test_second_option_cannot_be_misread_as_third():
    state,res=published_offer()
    port=make_port('second option',state,inbound='inbound-2')
    r=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                   'date_str':'2026-11-27','start_time':'12:00'},S)
    assert r['error_code']=='SELECTION_EVIDENCE_REQUIRED'

@pytest.mark.parametrize('selection', ['OK','Yes','something else','I prefer next month'])
def test_selection_needs_explicit_hour_or_valid_ordinal(selection):
    state,res=published_offer();port=make_port(selection,state)
    outcome=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                        'date_str':'2026-11-27','start_time':'11:00'},S)
    assert outcome['error_code']=='SELECTION_EVIDENCE_REQUIRED'


def test_unoffered_slot_never_accepted():
    state,res=published_offer();port=make_port('11:30',state)
    outcome=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                        'date_str':'2026-11-27','start_time':'11:30'},S)
    assert outcome['error_code']=='SLOT_NOT_OFFERED'


def test_expired_slot_rejected():
    state,res=published_offer();port=make_port('option 2',state,now=NOW+timedelta(hours=1))
    outcome=port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                        'date_str':'2026-11-27','start_time':'11:00'},S)
    assert outcome['error_code']=='DELIVERED_OFFER_REQUIRED'


def confirmed_draft():
    state,res=published_offer()
    port=make_port('second option',state,inbound='select-2')
    port.invoke('select_visit_time',{'proposal_id':res['proposal_id'],
                'date_str':'2026-11-27','start_time':'11:00'},S)
    return port.state,res


def booking_args(res):
    return {'unit_id':'H-201','proposal_id':res['proposal_id'],
            'date_str':'2026-11-27','start_time':'11:00',
            'first_name':'Buyer','last_name':'A','email':'demo@invalid.test','phone':'000'}


def test_booking_requires_real_delivered_recap():
    state,res=confirmed_draft()
    port=make_port('I confirm',state,inbound='confirm-3')
    assert port.invoke('book_onsite_visit',booking_args(res),S)['error_code']=='BOOKING_CONFIRMATION_REQUIRED'

@pytest.mark.parametrize('reply', ['OK','sure','yes', 'I guess so'])
def test_ambiguous_yes_never_commits_booking(reply):
    state,res=confirmed_draft()
    state['confirmation_request'].update(status='awaiting_confirmation',recap_message_id='reply-2')
    port=make_port(reply,state,inbound='confirm-3')
    assert port.invoke('book_onsite_visit',booking_args(res),S)['error_code']=='EXPLICIT_BOOKING_CONSENT_REQUIRED'


def test_explicit_confirm_stages_backend_commit_without_claiming_success():
    state,res=confirmed_draft()
    state['confirmation_request'].update(status='awaiting_confirmation',recap_message_id='reply-2')
    port=make_port('Yes, I confirm the visit',state,inbound='confirm-3')
    r=port.invoke('book_onsite_visit',booking_args(res),S)
    assert r['status']=='pending_backend_commit' and r['booking_confirmed'] is False
    assert port.state['confirmation_request']['confirmed_inbound_message_id']=='confirm-3'


def test_booking_args_must_match_verified_selection():
    state,res=confirmed_draft()
    state['confirmation_request'].update(status='awaiting_confirmation',recap_message_id='reply-2')
    port=make_port('I confirm the visit',state,inbound='confirm-3')
    args=booking_args(res);args['start_time']='12:00'
    assert port.invoke('book_onsite_visit',args,S)['error_code']=='BOOKING_DETAILS_MISMATCH'


def test_unrequested_media_is_not_shared():
    port=make_port('Tell me the price')
    r=port.invoke('get_unit_media',{'unit_id':'H-201'},S)
    assert r['error_code']=='MEDIA_REQUEST_REQUIRED'
    assert port.state.get('offered_assets')=={}


def test_media_needs_reviewed_target_coverage():
    port=make_port('Show the floor plan',material_reader=lambda *args:False)
    r=port.invoke('get_unit_media',{'unit_id':'H-201'},S)
    assert r['delivery']=='unavailable' and r['share_issued'] is False


def test_media_is_drafted_never_issued_by_hermes():
    port=make_port('Show the floor plan',material_reader=lambda *args:True)
    r=port.invoke('get_unit_media',{'unit_id':'H-201'},S)
    assert r['delivery']=='pending_backend_share' and r['share_issued'] is False
    assert port.state['offered_assets']['pending_request']['asset_ids']==['asset-1']
    assert 'url' not in r


def test_cancellation_needs_direct_buyer_request():
    port=make_port('Tell me about that visit',meeting_reader=lambda x:fake_meeting())
    r=port.invoke('cancel_onsite_visit',{'meeting_id':'meeting-1'},S)
    assert r['error_code']=='CANCELLATION_CONSENT_REQUIRED'


def test_cancel_drafts_intent_without_changing_meeting():
    meeting=fake_meeting()
    port=make_port('Please cancel my visit',meeting_reader=lambda x:meeting)
    r=port.invoke('cancel_onsite_visit',{'meeting_id':'meeting-1'},S)
    assert r['status']=='pending_backend_commit'
    assert port.state['confirmation_request']['booking_sha256']==booking_fingerprint(meeting)
    assert meeting.status.value=='confirmed'


def test_cross_project_meeting_is_never_staged():
    other=fake_meeting();other.project_id='p-other'
    port=make_port('Cancel my appointment',meeting_reader=lambda x:other)
    assert port.invoke('cancel_onsite_visit',{'meeting_id':'meeting-1'},S)['error_code']=='MEETING_NOT_FOUND'


def test_rescheduling_requires_fresh_offered_time():
    port=make_port('Reschedule my appointment',meeting_reader=lambda x:fake_meeting())
    args={'original_meeting_id':'meeting-1','proposal_id':'nonexistent',
          'date_str':'2026-11-27','start_time':'11:00','unit_id':'H-201'}
    r=port.invoke('reschedule_onsite_visit',args,S)
    assert r['error_code']=='FRESH_SLOT_REQUIRED'


def test_interest_does_not_infer_interest_from_a_fact_question():
    port=make_port('How many bedrooms?')
    r=port.invoke('track_property_interest',{'unit_id':'H-201','status':'interested'},S)
    assert r['error_code']=='INTEREST_EVIDENCE_REQUIRED'


def test_interested_statement_only_drafts_local_state():
    port=make_port("I'm interested in H-201")
    r=port.invoke('track_property_interest',{'unit_id':'H-201','status':'interested'},S)
    assert r['ok'] and not r['crm_updated']


def test_crm_write_held_for_later_evidence_contract():
    port=make_port('My email is a@example.invalid')
    r=port.invoke('update_lead_profile',{'email':'evil@invalid.test'},S)
    assert r['error_code']=='CRM_WRITE_DISABLED'


def test_runtime_requires_operational_port_marker():
    class Impostor:pass
    settings=HermesSettings(api_key='dummy')
    with pytest.raises(PermissionError,match='draft-only'):
        HermesSalesRuntime(settings,Impostor(),operational_draft_tools=P04_TOOL_NAMES)


def test_appointment_recap_requires_exact_property_date_time():
    req={'unit_id':'H-201','date':'2026-11-27','start_time':'11:00'}
    assert recap_visible('Please confirm visiting H-201 on 2026-11-27 at 11:00?',req)
    assert not recap_visible('Please confirm visiting H-201 on 2026-11-27 at 10:00?',req)
    assert not recap_visible('Your appointment is booked.',req)
    assert not recap_visible('Please confirm visiting H-202 on 2026-11-27 at 11:00?',req)


def test_only_actual_visible_menu_creates_selectable_authority():
    state,res=published_offer()
    menu=state['last_presented_choice_set']
    assert visible_menu('Available visit start times for H-201 on Friday, November 27, 2026:\n1. 10:00 AM\n2. 11:00 AM\n3. 12:00 PM',menu)
    assert not visible_menu('Available for H-201 on 2026-11-27: 10:00 11:00 12:00',menu)
    assert not visible_menu('1. 10:00 AM\n2. 11:00 AM\n3. 12:00 PM',menu)
