"""Live HEI-07B.5 evidence presentation; no LLM, provider, or DB writes.

Hermes chooses business tools. This module renders their verified operational
results and binds explicit selections to the actual delivered offer. It never
creates a meeting, generates an asset URL, or changes a primary preference.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo


GUIDANCE = (
    'Commercial activity is reversible: Exploration searches/compares; Details '
    'explains the selected property and materials; Visit plans an appointment. '
    'Keep primary preferences separate from temporary filters. Ask whether the '
    'buyer wants to replace existing preferences when a change is ambiguous. '
    'Keep the selected property and an independent visit draft during side questions. '
    'For visits first show numbered dates and all verified contiguous ranges; '
    'then show numbered hours for the chosen day only. Retain a requested '
    'morning/afternoon/evening filter on day selection. A range end includes the '
    'last hourly block; it is not another start time. Never expose advisors '
    'before a booking receipt. For a chosen hour, show one exact recap, with '
    'property, date, time, timezone and address, asking for Yes, I confirm. '
    'Never report a successful booking until its native receipt exists. '
    'For explicit photos/images use get_unit_media for the focused property. '
    'Do not claim absence based on an unexecuted or rejected tool. Offer one '
    'other approved resource or a visit after sharing materials.'
)


def _clock(value):
    return datetime.strptime(value, '%H:%M').strftime('%I:%M %p').lstrip('0')


def day_ranges(options, zone_name):
    """Union verified starts by local day; never fill a gap or reveal advisor IDs."""
    zone = ZoneInfo(zone_name)
    groups = {}
    for item in options:
        utc = datetime.fromisoformat(item['starts_at_utc'])
        if utc.tzinfo is None:
            raise ValueError('An aware availability timestamp is required')
        local = utc.astimezone(zone)
        if local.date().isoformat() != item['date'] or local.strftime('%H:%M') != item['start_time']:
            raise ValueError('Availability local time differs from UTC evidence')
        groups.setdefault(item['date'], {})[utc.astimezone(timezone.utc)] = local
    result = {}
    for day, values in sorted(groups.items()):
        ranges = []
        for utc, local in sorted(values.items()):
            end = (utc + timedelta(hours=1)).astimezone(zone)
            start_text = local.strftime('%H:%M')
            end_text = '24:00' if end.date() > local.date() and end.hour == 0 else end.strftime('%H:%M')
            if ranges and ranges[-1]['end_utc'] == utc and ranges[-1]['end'] == start_text:
                ranges[-1].update(last_start=start_text, end=end_text, end_utc=utc+timedelta(hours=1))
            else:
                ranges.append({'first_start':start_text, 'last_start':start_text,
                               'end':end_text,'end_utc':utc+timedelta(hours=1)})
        result[day] = [{k:v for k,v in r.items() if k != 'end_utc'} for r in ranges]
    return result


def enrich_slots(result, offer, draft, args):
    """Enrich the authorized tool result, retaining its exact native proposal."""
    if not result.get('ok') or not offer or result.get('proposal_id') != offer.get('proposal_id'):
        return result
    result = deepcopy(result)
    offer['menu_kind'] = 'visit_time' if result.get('date') else 'visit_day'
    offer['time_preference'] = args.get('time_preference') or 'any'
    if result.get('date'):
        draft['date'] = result['date']
    else:
        ranges = day_ranges(offer.get('options') or [], result['timezone'])
        result['available_dates'] = [
            {**entry,'first_start':ranges[entry['date']][0]['first_start'],
             'last_start':ranges[entry['date']][-1]['last_start'],
             'time_ranges':ranges[entry['date']]}
            for entry in result.get('available_dates') or [] if ranges.get(entry['date'])]
    return result


def _range_label(r):
    end = '12:00 AM (next day)' if r['end']=='24:00' else _clock(r['end'])
    return f"{_clock(r['first_start'])} - {end}"


def visit_menu(result, offer):
    """Exact verified labels, with one-option menus supported by live receipts."""
    from .contextual_choices import choice_from_slots
    from .commercial_delivery import clean_label
    menu = choice_from_slots(result)
    name = result.get('display_name')
    if not menu or not clean_label(name) or not clean_label(menu.get('timezone')):
        return None
    menu['display_name'] = name
    menu['proposal_id'] = offer['proposal_id']
    if menu['type']=='visit_day':
        dates = {x['date']:x for x in result['available_dates']}
        for option in menu['options']:
            ranges = dates[option['date']].get('time_ranges')
            if not ranges:
                return None
            option['label'] += ' | ' + ', '.join(_range_label(r) for r in ranges)
    return menu


def render_menu(menu):
    name, zone = menu['display_name'], menu['timezone']
    if menu['type']=='visit_day':
        head = f'Available days to visit {name} ({zone}):'
        tail = 'Which day works best for you? I will check the specific times for that day.'
    else:
        head = f'Available visit start times for {name} on {menu["date"]} ({zone}):'
        tail = 'Which time works best for you? The visit is not booked yet.'
    return head+'\n\n'+'\n'.join(f'{x["index"]}. {x["label"]}' for x in menu['options'])+'\n\n'+tail


def render_recap(request, name):
    from .commercial_delivery import clean_label
    from .bp_operation_receipts import recap_visible
    if not all(clean_label(x) for x in (name,request.get('visit_address'),request.get('timezone'))):
        return None
    request['display_name'] = name
    text = (f'Please review your visit to {name}:\n'
            f'Date: {request["date"]}\nTime: {request["start_time"]} ({request["timezone"]})\n'
            f'Location: {request["visit_address"]}\n'
            'Visit duration: 45 minutes. Not booked yet.\n\n'
            'Would you like to confirm this visit? Reply "Yes, I confirm".')
    return text if recap_visible(text,request) else None


# Bounded explicit acceptance of an already delivered exact recap. Not a
# generic yes/intent classifier and never used to authorize a material offer.
_BOOK_ACK = re.compile(
    r"\s*(?:yes[,! .]*\s*)?(?:i\s+)?confirm(?:\s+(?:this|the|my)\s+(?:visit|appointment|booking)|\s+that\s+it\s+is\s+correct)?[.!]?\s*"
    r"|\s*yes[, ]+that\s+is\s+correct[.!]?\s*"
    r"|\s*(?:s[ií][, ]+)?confirmo(?:\s+la\s+cita)?[.!]?\s*", re.I)


def booking_consent(text):
    from .bp_operational_port import AFFIRMATIVE
    return isinstance(text,str) and bool(AFFIRMATIVE.fullmatch(text) or _BOOK_ACK.fullmatch(text))


def draft_first_booking(port, args):
    """Live-only draft; the API independently verifies all evidence and books."""
    from .bp_operational_port import _fresh, _result
    req = port.state.get('confirmation_request') or {}
    offer = port.state.get('last_slot_search') or {}
    if (req.get('kind')!='book' or req.get('status')!='awaiting_confirmation'
            or not _fresh(req,port.now) or not _fresh(offer,port.now)
            or not req.get('recap_message_id') or req.get('recap_message_id')!=getattr(port,'latest_reply_id',None)
            or req.get('selected_inbound_message_id')==port.inbound_id):
        return _result('BOOKING_CONFIRMATION_REQUIRED','A fresh delivered full visit recap is required.')
    if (any(args.get(k)!=req.get(r) for k,r in [('proposal_id','proposal_id'),('unit_id','unit_id'),('date_str','date'),('start_time','start_time')])
            or offer.get('unit_id')!=req.get('unit_id') or offer.get('proposal_id')!=req.get('proposal_id')):
        return _result('BOOKING_DETAILS_MISMATCH','The selected visit differs from the recap.')
    if not booking_consent(port.message):
        return _result('EXPLICIT_BOOKING_CONSENT_REQUIRED','The buyer has not explicitly confirmed this visit.')
    port.state['confirmation_request']={**req,'status':'execution_requested','confirmed_inbound_message_id':port.inbound_id}
    return {'ok':True,'status':'pending_backend_commit','booking_confirmed':False,
            'next_action':'The backend must revalidate and persist the visit before confirming.'}


def prepare_confirmation(port, enabled):
    """Resolve explicit assent against the delivered recap, like the demo.

    Use the authorized native tool, not a direct effect or fabricated trace.
    """
    from .commercial_delivery import invoke_domain
    req = port.state.get('confirmation_request') or {}
    if (not (port.state.get('last_slot_search') or {}).get('menu_kind')
            or 'book_onsite_visit' not in enabled or not booking_consent(port.message)
            or req.get('status')!='awaiting_confirmation' or req.get('kind')!='book'):
        return None
    args={'proposal_id':req.get('proposal_id'),'unit_id':req.get('unit_id'),
          'date_str':req.get('date'),'start_time':req.get('start_time')}
    result=invoke_domain(port,'book_onsite_visit',args)
    if result.get('ok'):
        port.prepared_booking={'args':args,'result':deepcopy(result)}
        return result
    return None


def visit_reply(port, observations, enabled):
    """Render exact evidence only; unrelated actions are left to Hermes."""
    from .commercial_delivery import visible_name
    from .bp_operation_receipts import visible_menu
    req=port.state.get('confirmation_request') or {}
    if (req.get('kind')=='book' and req.get('status')=='recap_required'
            and req.get('selected_inbound_message_id')==port.inbound_id):
        reply=render_recap(req,visible_name(port,req.get('unit_id')))
        if reply:
            port.menus=[]
            return reply
    if not port.slot_batches or port.search_batches or port.comparison_batches or port.offered_media:
        return None
    allowed={'get_available_visit_slots','get_unit_details','get_project_overview','select_visit_time','list_unit_assets'}
    recoverable={'PROPERTY_REQUIRED','PROPERTY_NOT_FOUND_OR_AMBIGUOUS','UNSUPPORTED_PERIOD',
                 'VISIT_SELECTION_ALREADY_RESOLVED','DELIVERED_OFFER_REQUIRED'}
    for obs in observations:
        if obs.get('tool') not in allowed or (obs.get('status')!='executed' and obs.get('error_code') not in recoverable):
            return None
    batch=port.slot_batches[-1]
    result, offer = batch['result'], batch['offer']
    choice=port.choice or {}
    if choice.get('status')=='resolved' and choice.get('type')=='visit_day':
        if (result.get('date')!=(choice.get('choice') or {}).get('date') or offer.get('unit_id')!=choice.get('unit_id')):
            return None
    menu=visit_menu(result,offer)
    if not menu:
        if result.get('availability_status')=='NO_SLOTS' and result.get('display_name'):
            return f'No available visit times matched that request for {result["display_name"]}. Would another day or time work for you?'
        return None
    reply=render_menu(menu)
    if not visible_menu(reply,menu):
        return None
    # Bind only displayed starts to a time offer. A broad day menu is not a
    # time offer and cannot authorize a direct booking selection.
    if menu['type']=='visit_time':
        displayed={(x['date'],x['start_time']) for x in menu['options']}
        offer={**offer,'options':[x for x in offer['options'] if (x['date'],x['start_time']) in displayed]}
    port.state['last_slot_search']=deepcopy(offer)
    port.state['visit_draft']=deepcopy(batch['draft'])
    port.menus=[menu]
    return reply


_DIRECT_MEDIA=re.compile(r"\b(?:show|send|share|give|see|view|look at|have|access)\b",re.I)
_BLOCK_MEDIA=re.compile(r"\b(?:not|don't|do not|without|instead of|maybe|if|compare|book|cancel|reschedule|visit|price|budget)\b",re.I)


def recover_explicit_material(port, observations, enabled):
    """A narrow verified-read recovery for explicit material requests only.

    The native media tool retains approval, property and channel checks. No
    recovery for policy denials, ambiguous references, mixed goals or assent.
    """
    from .conversation_parity import focus_ref, media_tags
    from .commercial_delivery import invoke_domain
    text=port.message
    tags=media_tags(text)
    pending=(port.state.get('offered_assets') or {}).get('pending_request') or {}
    if (len(tags)!=1 or 'get_unit_media' not in enabled or not _DIRECT_MEDIA.search(text)
            or _BLOCK_MEDIA.search(text) or port.search_batches or port.slot_batches or port.comparison_batches
            or pending.get('source_inbound_message_id')==port.inbound_id):
        return None
    allowed={'get_unit_details','list_unit_assets','get_unit_media','get_project_overview'}
    for obs in observations:
        if obs.get('tool') not in allowed or (obs.get('status')!='executed' and obs.get('error_code') not in
                    {'PROPERTY_REFERENCE_CONFLICT','PROPERTY_NOT_FOUND_OR_AMBIGUOUS','MEDIA_TYPE_REQUIRED'}):
            return None
    ref=focus_ref(port.state)
    if not ref or (port.state.get('conversation_focus') or {}).get('ambiguous'):
        return None
    return invoke_domain(port,'get_unit_media',{'unit_id':ref})


def update_phase(port, prior):
    """Project evidenced activity into the existing persisted phase field."""
    from .conversation_parity import focus_ref
    state=port.state; req=state.get('confirmation_request') or {}
    pending=(state.get('offered_assets') or {}).get('pending_request') or {}
    if req.get('confirmed_inbound_message_id')==port.inbound_id or req.get('selected_inbound_message_id')==port.inbound_id:
        phase='visit_confirmation'
    elif port.slot_batches:
        phase='visit_planning'
    elif port.search_batches or port.comparison_batches:
        phase='property_exploration'
    elif (port.explicit_focus or pending.get('source_inbound_message_id')==port.inbound_id
            or (focus_ref(state) and getattr(port,'details_read',False))):
        phase='property_details'
    else:
        return
    state['conversation_phase']=phase
    draft=state.get('visit_draft') or {}
    if draft.get('unit_id') and draft.get('status') not in {'idle','confirmed','committed','cancelled','rescheduled'}:
        state['visit_planning_paused']=phase in {'property_exploration','property_details'}
