"""Native live journey contracts; no external provider calls."""
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from copy import deepcopy
import pytest
from app.modules.hermes_sales_core import journey_contract as j

ZONE = 'America/Denver'

def slot(day, hour):
    local = datetime(2026, 12, day, hour, tzinfo=ZoneInfo(ZONE))
    return {'date':local.date().isoformat(), 'start_time':local.strftime('%H:%M'),
            'starts_at_utc':local.astimezone(timezone.utc).isoformat()}


def test_contiguous_union_and_gap():
    starts=[slot(4,h) for h in (9,10,11,14,15,16)]
    ranges=j.day_ranges(starts+[slot(4,10)],ZONE)
    assert ranges['2026-12-04']==[
        {'first_start':'09:00','last_start':'11:00','end':'12:00'},
        {'first_start':'14:00','last_start':'16:00','end':'17:00'}]


def test_range_has_no_advisor_identity():
    starts=[{**slot(4,9),'advisor_id':'private'}]
    assert j.day_ranges(starts,ZONE)=={'2026-12-04':[{'first_start':'09:00','last_start':'09:00','end':'10:00'}]}


def test_invalid_local_timestamp_rejected():
    with pytest.raises(ValueError):j.day_ranges([{**slot(4,9),'start_time':'10:00'}],ZONE)


def test_weekly_ranges_preserve_native_proposal():
    offer={'proposal_id':'native','options':[slot(d,h) for d in (2,4,5) for h in range(9,17)]}
    result={'ok':True,'proposal_id':'native','timezone':ZONE,'available_dates':[{'date':f'2026-12-{d:02}'} for d in (2,4,5)]}
    enriched=j.enrich_slots(result,offer,{}, {'time_preference':'morning'})
    assert offer['menu_kind']=='visit_day' and offer['time_preference']=='morning'
    assert len(enriched['available_dates'])==3
    assert all(r['first_start']=='09:00' and r['last_start']=='16:00' for r in enriched['available_dates'])
    assert 'time_ranges' not in result['available_dates'][0]


def test_exact_day_records_date():
    offer={'proposal_id':'native','options':[slot(4,10)]};draft={}
    result={'ok':True,'proposal_id':'native','timezone':ZONE,'date':'2026-12-04','available_slots':[slot(4,10)]}
    j.enrich_slots(result,offer,draft,{})
    assert offer['menu_kind']=='visit_time' and draft['date']=='2026-12-04'


def test_one_option_render_is_numbered():
    menu={'type':'visit_time','display_name':'Van Buren','timezone':ZONE,'date':'2026-12-04','options':[{'index':1,'label':'10:00 AM'}]}
    assert '1. 10:00 AM' in j.render_menu(menu)
    assert 'not booked yet' in j.render_menu(menu)


def test_range_end_midnight():
    ranges=j.day_ranges([slot(4,23)],ZONE)
    assert ranges['2026-12-04'][0]['end']=='24:00'
    assert 'next day' in j._range_label(ranges['2026-12-04'][0])


@pytest.mark.parametrize('message',['I confirm','Yes, I confirm','Yes, that is correct','I confirm that it is correct','Sí, confirmo'])
def test_explicit_confirmation_variants(message):
    assert j.booking_consent(message)


@pytest.mark.parametrize('message',['yes','ok','no, I confirm nothing','I confirm but change the date','send me the brochure','I confirm the price'])
def test_unrelated_or_ambiguous_confirmation_rejected(message):
    assert not j.booking_consent(message)


def test_recap_binds_exact_visible_facts():
    from app.modules.hermes_sales_core.bp_operation_receipts import recap_visible
    req={'unit_id':'internal-uuid','date':'2026-12-04','start_time':'10:00','timezone':ZONE,'visit_address':'123 Main Street'}
    reply=j.render_recap(req,'Van Buren')
    assert reply and recap_visible(reply,req)
    assert 'internal-uuid' not in reply
    assert '123 Main Street' in reply and ZONE in reply
    assert not recap_visible(reply.replace('10:00','11:00'),req)


def test_day_menu_and_exact_day_selection():
    from app.modules.hermes_sales_core.contextual_choices import resolve
    from app.modules.hermes_sales_core.bp_operation_receipts import visible_menu
    offer={'proposal_id':'native','options':[slot(d,h) for d in (2,4,5) for h in range(9,17)]}
    result={'ok':True,'unit_id':'house','display_name':'Van Buren','proposal_id':'native','timezone':ZONE,'available_dates':[{'date':f'2026-12-{d:02}'} for d in (2,4,5)]}
    menu=j.visit_menu(j.enrich_slots(result,offer,{},{}),offer)
    assert '9:00 AM - 5:00 PM' in j.render_menu(menu)
    assert visible_menu(j.render_menu(menu),menu)
    assert resolve({'last_presented_choice_set':menu},'Option 3')['choice']['date']=='2026-12-05'


def test_single_time_menu_proof():
    from app.modules.hermes_sales_core.bp_operation_receipts import visible_menu
    offer={'proposal_id':'native','options':[slot(4,10)]}
    result={'ok':True,'unit_id':'house','display_name':'Van Buren','proposal_id':'native','timezone':ZONE,'date':'2026-12-04','available_slots':[slot(4,10)]}
    menu=j.visit_menu(result,offer)
    assert visible_menu(j.render_menu(menu),menu)
    assert not visible_menu(j.render_menu(menu).replace('10:00 AM','11:00 AM'),menu)
