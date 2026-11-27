"""Demo delivery parity: presentation of trusted, current-turn domain evidence.

No second model, new router, external effect or synthetic receipt. The live
adapter owns the actual tools, authorization and state; this module only
reconciles a narrow read/selection contract. Unproved cases stay fail-closed.
"""
from copy import deepcopy
import re

from . import commercial_turn, sales_preferences

_READS = frozenset({'search_properties', 'evaluate_properties_for_lead',
                    'get_project_overview', 'update_search_preferences'})
_VISITS = frozenset({'get_available_visit_slots', 'get_unit_details',
                     'get_project_overview', 'select_visit_time'})
_OTHER = re.compile(r'\b(?:also|then|send|share|compare|finance|mortgage|discount|'
                    r'cancel|reschedule|book|location|address|parking|garden|'
                    r'kitchen|area|bathrooms?|features|details)\b', re.I)


def clean_label(value):
    return (isinstance(value, str) and 0 < len(value) <= 160 and
            not re.search(r'[\x00-\x1f\x7f<>\[\]`*]|https?://', value, re.I))


def safe_tools(observations, allowed):
    """Never repair a turn containing unrelated operations or unknown failures."""
    from .numbered_catalog import RECOVERABLE_SEARCH_ERRORS
    if not isinstance(observations, list):
        return False
    for event in observations:
        if not isinstance(event, dict) or event.get('tool') not in allowed:
            return False
        if event.get('status') == 'executed' and event.get('error_code') is None:
            continue
        if (event.get('tool') == 'search_properties' and event.get('status') == 'rejected'
                and event.get('error_code') in RECOVERABLE_SEARCH_ERRORS):
            continue
        return False
    return True


def primary_declaration(message, state):
    """Reuse the demo-derived declaration parser, never infer a revision from a search."""
    if ('?' in message or _OTHER.search(message) or commercial_turn.search_request(message)
            or not re.search(r'\b(?:i|we|my|our)\b',message,re.I)
            or re.search(r'\b(?:temporarily|hypothetically|for comparison|for now|maybe|what if|if|unless|suppose)\b',message,re.I)
            or commercial_turn.intent(message) != 'preference_update'):
        return {}
    changes = sales_preferences.parse_declarations(message)
    if not changes or commercial_turn.scope(message, bool((state.get('search_preferences') or {}).get('revision'))) != 'permanent':
        return {}
    # The current preference contract is USD only. Do not interpret foreign
    # currency declarations through the USD parser.
    if 'budget' in changes and (not re.search(r'\$|\bUSD\b', message, re.I)
                                or re.search(r'\b(?:MXN|PEN|EUR|CAD|GBP|BRL|COP|ARS|CLP|pesos?|soles|euros?)\b|[€£]', message, re.I)):
        return {}
    return changes


def primary_ack(port, observations):
    """A verified declaration is not an approved listing price."""
    if not getattr(port, 'primary_captured', False) or not safe_tools(observations, _READS):
        return None
    prefs = port.state.get('search_preferences') or {}
    declared = primary_declaration(port.message, port.state)
    if not prefs.get('revision') or not declared:
        return None
    # No new listing price claim, no new search, no inferred consent.
    from app.modules.money import format_amount
    lines = []
    cap = (declared.get('budget') or {}).get('maximum_usd')
    if cap is not None and cap == (prefs.get('budget') or {}).get('maximum_usd'):
        lines.append(f'Your budget limit is USD {format_amount(cap)}.')
    beds = declared.get('bedrooms') or {}
    if beds.get('mode') == 'exact' and beds.get('preferred') == (prefs.get('bedrooms') or {}).get('preferred'):
        lines.append(f"I've noted that you need exactly {beds['preferred']} bedrooms.")
    if not lines:
        lines.append("I've noted your search preferences.")
    port.menus = []
    port.state['last_presented_units'] = []
    return ' '.join(lines + ['Would you like to explore properties that match your preferences?'])


def explicit_search_filters(message):
    """Existing parser, restricted to uncomplicated bedroom/price searches."""
    if (not commercial_turn.search_request(message) or _OTHER.search(message)
            or re.search(r'\b(?:at least|minimum|maximum bedrooms|or more|or fewer|between|except|unless|not|with a|with an|near)\b',message,re.I)):
        return None
    requested = commercial_turn.extracted_criteria(message)
    if set(requested) != {'bedrooms', 'max_price_usd'} or not re.search(r'\$|\bUSD\b', message, re.I):
        return None
    if re.search(r'\b(?:MXN|PEN|EUR|CAD|GBP|BRL|COP|ARS|CLP|pesos?|soles|euros?)\b|[€£]', message, re.I):
        return None
    return requested


def reconcile_temporary_filters(message, state, args):
    """Respect explicit temporary criteria, without revising primary preferences.

    Only applies to an existing primary profile and the search tool that Hermes
    has actually selected. Unsupported/compound filters stay on the native path.
    """
    prefs = state.get('search_preferences') or {}
    if not prefs.get('revision') or commercial_turn.scope(message, True) != 'temporary':
        return args
    requested = explicit_search_filters(message)
    raw = args.get('criteria') or {}
    if (not requested or not isinstance(raw,dict) or args.get('scope') not in (None,'temporary')
            or set(raw)-{'bedrooms','bedrooms_any','bedrooms_min','bedrooms_max','max_price_usd','relative_price_lt'}):
        return args
    # Do not treat this as an instruction to update preferences. In particular
    # do not let a saved cap silently replace the buyer's exploratory ceiling.
    return {**args,'scope':'temporary','criteria':requested}


def exact_search(batch, message, inbound_id):
    """Bind simple explicit filters to one complete executed result, not a union."""
    requested = explicit_search_filters(message)
    if not requested:
        return False
    search = batch.get('search') or {}
    actual = dict(search.get('criteria') or {})
    beds, cap = requested['bedrooms'], requested['max_price_usd']
    if actual.get('bedrooms_any') == [beds]:
        actual.pop('bedrooms_any'); actual.setdefault('bedrooms', beds)
    if actual.get('bedrooms_min') == actual.get('bedrooms_max') == beds:
        actual.pop('bedrooms_min'); actual.pop('bedrooms_max'); actual.setdefault('bedrooms', beds)
    if actual.get('bedrooms') == beds:
        for key in ('bedrooms_min','bedrooms_max'):
            if actual.get(key) == beds:
                actual.pop(key)
    strict = bool(re.search(r'\b(?:under|below|less than)\b', message, re.I))
    if strict and actual.get('relative_price_lt') == cap:
        actual.pop('relative_price_lt'); actual.setdefault('max_price_usd', cap)
    rows = batch.get('rows')
    if (actual != requested or search.get('scope') != 'temporary'
            or search.get('source_inbound_message_id') != inbound_id
            or not isinstance(rows, list) or search.get('match_count') != len(rows)):
        return False
    from app.modules.money import parse_amount
    try:
        return all(row.get('bedrooms') == beds and row.get('currency') == 'USD'
                   and parse_amount(row.get('price')) <= cap
                   and (not strict or parse_amount(row.get('price')) < cap)
                   for row in rows)
    except (ValueError, TypeError, AttributeError):
        return False


def search_reply(port, observations, channel, *, monetary_rejected=False):
    """Zero-match delivery, or bounded repair of an actual single match.

    Multi-property listings retain numbered_catalog's existing proof. No
    alternatives are invented; unknown inventory is not a negative fact.
    """
    if not safe_tools(observations, _READS) or port.offered_media:
        return None
    batches = port.search_batches
    if not batches or batches[-1]['search'] != port.state.get('active_search'):
        return None
    batch = batches[-1]
    if not exact_search(batch, port.message, port.inbound_id):
        return None
    rows = batch['rows']
    if not rows and monetary_rejected:
        port.menus = []
        port.state['last_presented_units'] = []
        from app.modules.money import format_amount
        criteria=explicit_search_filters(port.message)
        return (f'Your budget limit for this search is USD {format_amount(criteria["max_price_usd"])}. '
                f'I found no verified matches for the requested {criteria["bedrooms"]} bedrooms. '
                'Would you like to adjust a criterion?')
    if not monetary_rejected or len(rows) != 1:
        return None
    from .conversation_parity import display_name
    from app.modules.money import format_amount, parse_amount
    row = rows[0]; name = display_name(row)
    if (not clean_label(name) or row.get('kind') not in {'unit', 'property_type'}
            or row.get('availability_verified') is not True
            or (row['kind'] == 'property_type' and (type(row.get('available_units')) is not int or row['available_units'] <= 0))):
        return None
    label = 'starting price' if row['kind'] == 'property_type' else 'listing price'
    amount = format_amount(parse_amount(row['price']))
    port.menus = []
    port.state['last_presented_units'] = [row['reference']]
    return f'{name}: {row["bedrooms"]} bedrooms; {label} USD {amount}. Would you like to explore this property?'


def verified_budget_profile(port, observations, lead_profile):
    """Ephemeral evidence for our canonical repair ONLY, not the model reply.

    Reuse the existing monetary guard's explicit buyer-budget exemption. Never
    add a search ceiling to the set of approved listing prices or store it as
    a persistent CRM budget. Unrelated, previous and speculative amounts do
    not become evidence for this repair.
    """
    if not safe_tools(observations, _READS):
        return lead_profile
    cap = None
    batches = port.search_batches
    if (batches and batches[-1]['search'] == port.state.get('active_search')
            and exact_search(batches[-1],port.message,port.inbound_id)):
        cap = explicit_search_filters(port.message)['max_price_usd']
    elif getattr(port,'primary_captured',False):
        declared = primary_declaration(port.message,port.state)
        current = (port.state.get('search_preferences') or {}).get('budget') or {}
        value = (declared.get('budget') or {}).get('maximum_usd')
        if value is not None and value == current.get('maximum_usd'):
            cap = value
    if type(cap) is not int or cap <= 0:
        return lead_profile
    profile = deepcopy(lead_profile) if isinstance(lead_profile,dict) else {}
    facts = profile.get('facts')
    if not isinstance(facts,dict):
        facts = {}
    else:
        facts = deepcopy(facts)
    facts.pop('budget_minimum',None);facts.pop('budget_maximum',None)
    facts['budget'] = {'value': {'maximum':cap,'currency':'USD'}}
    facts['budget_currency'] = {'value':'USD'}
    profile['facts']=facts
    return profile


def visible_name(port, ref):
    """Only a unique approved label from the scoped catalog, never model text."""
    from .conversation_parity import display_name
    row = port._resolve(ref)
    if not row:
        return None
    name = display_name(row)
    if not clean_label(name):
        return None
    matches = {r['reference'] for r in port._all_rows() if display_name(r).casefold() == name.casefold()}
    return name if matches == {row['reference']} else None


def compare_reply(port, observations):
    """Render a specific count comparison from successful read-tool facts."""
    if not safe_tools(observations, {'compare_properties', 'get_unit_details', 'get_project_overview'}):
        return None
    named = getattr(port, 'comparison_rows', [])
    if len(named) != 2 or not getattr(port, 'comparison_batches', []):
        return None
    text = port.message
    fields = [field for field in ('bathrooms', 'bedrooms') if re.search(r'\b'+field+r'?\b', text, re.I)]
    # Compound factual requests remain Hermes's responsibility.
    if len(fields) != 1 or re.search(r'\b(?:prices?|costs?|budgets?|areas?|parking|kitchens?|locations?|available|availability|send|share|visit|also|then|features)\b', text, re.I):
        return None
    field = fields[0]
    refs = {r['reference'] for r in named}
    for rows in reversed(port.comparison_batches):
        if len(rows) != 2 or {r['reference'] for r in rows} != refs:
            continue
        values = [r.get(field) for r in rows]
        names = [visible_name(port, r['reference']) for r in rows]
        if not all(names) or any(type(v) not in (int,float) or not 0 <= v <= 100 or int(v) != v for v in values):
            continue
        unit = field[:-1]
        lines = [f'{n}: {int(v)} {unit if v == 1 else field}.' for n,v in zip(names,values)]
        if values[0] == values[1]:
            lines.append(f'Both have the same number of {field}.')
        else:
            winner = 0 if values[0] > values[1] else 1
            lines.append(f'{names[winner]} has more {field}.')
        return '\n'.join(lines)
    return None


def visit_reply(port, observations, enabled):
    """Publish the same typed availability/recap contract as demo v13.3.3.

    A recovery read or selection uses the already authorized native port;
    never replay a booking or create a new external effect.
    """
    from .contextual_choices import choice_from_slots, explicit_date
    from .bp_operation_receipts import recap_visible, visible_menu
    from .conversation_parity import focus_ref
    if (not safe_tools(observations, _VISITS) or port.offered_media
            or re.search(r'\b(?:also|then|send|share|cancel|reschedule|compare|instead)\b',port.message,re.I)):
        return None
    choice = port.choice or {}
    kind = choice.get('type') if choice.get('status') == 'resolved' else None
    # A typed time is explicit selection evidence, not booking consent.
    if kind == 'visit_time':
        req = port.state.get('confirmation_request') or {}
        picked = choice.get('choice') or {}
        prior = getattr(port,'prior_visit_offer',None) or {}
        if (prior.get('proposal_id') == picked.get('proposal_id') and prior.get('source_reply_message_id')
                and prior.get('unit_id') == choice.get('unit_id')):
            if (req.get('selected_inbound_message_id') != port.inbound_id
                    or req.get('proposal_id') == prior['proposal_id']):
                port.state['last_slot_search']=deepcopy(prior)
                if req.get('selected_inbound_message_id') != port.inbound_id:
                    port.state['visit_draft']=deepcopy(port.prior_visit_draft)
        if (req.get('selected_inbound_message_id') != port.inbound_id
                and 'select_visit_time' in enabled):
            port.invoke('select_visit_time', {'proposal_id':picked.get('proposal_id'),
                'date_str':picked.get('date'), 'start_time':picked.get('start_time')}, port.snapshot.scope)
    req = port.state.get('confirmation_request') or {}
    if (req.get('kind') == 'book' and req.get('status') == 'recap_required'
            and req.get('selected_inbound_message_id') == port.inbound_id):
        name = visible_name(port, req.get('unit_id'))
        address, zone = req.get('visit_address'), req.get('timezone')
        if not name or not clean_label(address) or not clean_label(zone):
            return None
        req['display_name'] = name
        reply = (f'Your visit to {name}: {req["date"]} at {req["start_time"]} ({zone}). '
                 f'Location: {address}. It is not booked yet. Would you like to confirm this visit?')
        if recap_visible(reply, req):
            port.menus = []
            return reply
        return None
    if 'get_available_visit_slots' not in enabled or kind == 'visit_time':
        return None
    if kind == 'visit_day':
        expected_date = (choice.get('choice') or {}).get('date')
        ref = choice.get('unit_id')
        expected_kind = 'visit_time'
    else:
        if (commercial_turn.intent(port.message) != 'visit_planning' or
                re.search(r'\b(?:also|then|send|share|cancel|reschedule|book|compare|morning|afternoon|evening)\b',port.message,re.I)):
            return None
        if not getattr(port, 'slot_batches', []):
            return None
        ref = focus_ref(port.state)
        # For explicitly scoped periods, keep the tool's scope rather than
        # extending it. General day requests may recover an upcoming-days read.
        expected_date = None
        expected_kind = 'visit_day'
        explicit = explicit_date(port.message, anchor_year=port.now.year)
        if explicit or re.search(r'\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',port.message,re.I):
            return None
    if not ref:
        return None
    period = re.search(r'\b(?:this|next)\s+(?:weekend|week)\b',port.message,re.I)
    general = kind is None and period is None
    def eligible(batch):
        offer = batch['offer']; menu = choice_from_slots(batch['result'])
        args = batch.get('args') or {}
        raw = str(args.get('date_str') or '').strip().casefold()
        if args.get('time_preference') not in (None,'any'):
            return False
        if expected_kind == 'visit_day' and ((general and raw not in ('','upcoming days'))
                or (period and raw != period.group(0).casefold())):
            return False
        return (menu and offer.get('source_inbound_message_id') == port.inbound_id
                and offer.get('unit_id') == ref and menu['type'] == expected_kind
                and (expected_date is None or menu.get('date') == expected_date))
    batches = [b for b in port.slot_batches if eligible(b)]
    if not batches and (kind == 'visit_day' or general):
        args = {'date_str': expected_date or 'upcoming days'}
        port.invoke('get_available_visit_slots',args,port.snapshot.scope)
        batches = [b for b in port.slot_batches if eligible(b)]
    if not batches:
        return None
    batch = batches[-1]; menu = choice_from_slots(batch['result']); offer = batch['offer']
    if len(menu['options']) < 2:
        # Single-slot receipt semantics are deliberately not changed here.
        return None
    name = visible_name(port, ref); zone = menu.get('timezone')
    if not name or not clean_label(zone):
        return None
    menu['display_name'] = name
    # Day menus also bind the exact proposal; no hidden later result can be
    # substituted by the receipt stage.
    menu['proposal_id'] = offer['proposal_id']
    if expected_kind == 'visit_day':
        head = f'Available days to visit {name} ({zone}):'
        tail = 'Which day works best for you?'
    else:
        head = f'Available visit start times for {name} on {menu["date"]} ({zone}):'
        tail = 'Which time works best for you? The visit is not booked yet.'
    reply = head + '\n\n' + '\n'.join(f'{o["index"]}. {o["label"]}' for o in menu['options']) + '\n\n' + tail
    if not visible_menu(reply, menu):
        return None
    port.state['last_slot_search'] = deepcopy(offer)
    port.state['visit_draft'] = deepcopy(batch['draft'])
    port.menus = [menu]
    return reply
