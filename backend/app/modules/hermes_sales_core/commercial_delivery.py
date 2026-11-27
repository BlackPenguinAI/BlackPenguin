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


# Recognize only an entire explicit two-filter catalog request when repairing
# arguments or recovering omitted reads. This is a narrow evidence contract,
# not a general intent classifier; unaccounted-for qualifiers stay with Hermes.
_COUNT = r'(?:[1-9]|1\d|20|one|two|three|four|five|six)\s*[- ]?\s*(?:bedrooms?|beds?)'
_HOME = r'(?:houses|homes|properties)'
_CAP = r'(?:under|below|less than|up to|at most)\s*(?:USD\s*\$?\s*|\$\s*)\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[km])?'
_SIMPLE_FILTER_REQUEST = re.compile(
    r'\s*(?:please\s+)?(?:show(?:\s+me)?|list|find(?:\s+me)?|give\s+me|which|what|do\s+you\s+have|are\s+there)\s+'
    r'(?:the\s+|any\s+)?(?:available\s+)?(?:'+_COUNT+r'\s+'+_HOME+r'|'+_HOME+r'\s+with\s+'+_COUNT+r')'
    r'\s+(?:are\s+)?'+_CAP+r'(?:\s+(?:(?:as|in)\s+(?:a\s+)?numbered\s+list|(?:just\s+)?for\s+comparison))?[.!?]?\s*',re.I)


def explicit_search_filters(message):
    """Existing parser, restricted to uncomplicated bedroom/price searches."""
    if not _SIMPLE_FILTER_REQUEST.fullmatch(message):
        return None
    if (not commercial_turn.search_request(message) or _OTHER.search(message)
            or re.search(r'\b(?:at least|minimum|maximum bedrooms|or more|or fewer|between|except|unless|not|with a|with an|near)\b',message,re.I)):
        return None
    normalized = re.sub(r'\bUSD\s*\$?\s*(?=\d)', '$', message, flags=re.I)
    requested = commercial_turn.extracted_criteria(normalized)
    if set(requested) != {'bedrooms', 'max_price_usd'} or not re.search(r'\$|\bUSD\b', message, re.I):
        return None
    if re.search(r'\b(?:MXN|PEN|EUR|CAD|GBP|BRL|COP|ARS|CLP|pesos?|soles|euros?)\b|[€£]', message, re.I):
        return None
    return requested


def reconcile_temporary_filters(message, state, args):
    """Respect explicit temporary criteria, without revising primary preferences.

    Applies to explicit searches even before a primary profile exists.
    Unsupported/compound filters stay on the native path.
    """
    prefs = state.get('search_preferences') or {}
    if primary_declaration(message, state) or commercial_turn.clear_permanent_revision(message):
        return args
    if prefs.get('revision') and commercial_turn.scope(message, True) != 'temporary':
        return args
    requested = explicit_search_filters(message)
    raw = args.get('criteria') or {}
    if (not requested or not isinstance(raw,dict) or args.get('scope') not in (None,'temporary')
            or set(raw)-{'bedrooms','bedrooms_any','bedrooms_min','bedrooms_max','max_price_usd','relative_price_lt'}):
        return args
    # Do not treat this as an instruction to update preferences. In particular
    # do not let a saved cap silently replace the buyer's exploratory ceiling.
    return {**args,'scope':'temporary','criteria':requested}


def strict_search_bounds(message, args):
    """Use the existing exclusive-price filter for 'under', not an inclusive cap.

    Keep max_price_usd as the buyer's displayed limit for existing contracts.
    Unknown/compound searches are not rewritten by this helper.
    """
    requested=explicit_search_filters(message)
    raw=args.get('criteria') or {}
    if (not requested or not isinstance(raw,dict) or args.get('scope') not in (None,'temporary')
            or raw!=requested or not re.search(r'\b(?:under|below|less than)\b',message,re.I)):
        return args
    return {**args,'criteria':{**raw,'relative_price_lt':requested['max_price_usd']}}


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


def search_reply(port, observations, channel, *, monetary_rejected=False, model_reply=None):
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
    if not rows:
        port.menus = []
        port.state['last_presented_units'] = []
        from app.modules.money import format_amount
        criteria=explicit_search_filters(port.message)
        return (f'Your budget limit for this search is USD {format_amount(criteria["max_price_usd"])}. '
                f'I found no verified matches for the requested {criteria["bedrooms"]} bedrooms. '
                'Would you like to adjust a criterion?')
    if len(rows) != 1:
        return None
    from .conversation_parity import display_name
    from app.modules.money import format_amount, parse_amount
    row = rows[0]; name = display_name(row)
    if (not clean_label(name) or row.get('kind') not in {'unit', 'property_type'}
            or row.get('availability_verified') is not True
            or (row['kind'] == 'property_type' and (type(row.get('available_units')) is not int or row['available_units'] <= 0))):
        return None
    if (not monetary_rejected and isinstance(model_reply, str)
            and re.search(r'(?<![\w-])'+re.escape(name)+r'(?![\w-])', model_reply, re.I)
            and not re.search(r'\b(?:no (?:verified |matching )?matches|cannot find|could not find)\b', model_reply,re.I)):
        return None  # preserve a grounded natural answer
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
    if (not safe_visit_tools(port, observations) or port.offered_media
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
            invoke_domain(port, 'select_visit_time', {'proposal_id':picked.get('proposal_id'),
                'date_str':picked.get('date'), 'start_time':picked.get('start_time')})
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
        if (not broad_visit_request(port.message) or
                re.search(r'\b(?:also|then|send|share|cancel|reschedule|book|compare|morning|afternoon|evening)\b',port.message,re.I)):
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
        invoke_domain(port, 'get_available_visit_slots', args)
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


# The demo's begin_turn/verify_explicit_preferences and v13.3.3 typed choice
# hooks are adapted here to the existing authorized live port. No extra model.
def invoke_domain(port, tool, args):
    """Actual authorized domain call, recorded separately from SDK tool calls."""
    result = port.invoke(tool, args, port.snapshot.scope)
    if hasattr(port, 'domain_observations'):
        port.domain_observations.append({'tool':tool,
            'status':'executed' if result.get('ok') else 'rejected',
            'error_code':result.get('error_code')})
    return result


def capture_primary(port, enabled):
    """Return the exact validated preference snapshot; no profile write here."""
    if 'update_search_preferences' not in enabled:
        return None
    declared = primary_declaration(port.message, port.state)
    if not declared:
        return None
    before = deepcopy(port.state.get('search_preferences') or {})
    expected_state = deepcopy(port.state)
    expected = sales_preferences.apply(expected_state, declared, source_message_id=port.inbound_id)
    if not expected.get('ok'):
        return None
    outcome = invoke_domain(port, 'update_search_preferences', {})
    after = port.state.get('search_preferences') or {}
    # A repeated same declaration may legitimately leave the revision intact.
    # A changed declaration must bind to this authenticated inbound.
    if (not outcome.get('ok') or not after.get('revision')
            or after != expected_state.get('search_preferences')
            or (after != before and after.get('last_source_message_id') != port.inbound_id)):
        return None
    port.primary_captured = True
    return deepcopy(after)


def broad_visit_request(message):
    """Day availability is not a property search merely because it says options."""
    return bool(re.search(r'\b(?:visit|tour|appointment)\b', message,re.I)
        and re.search(r'\b(?:days?|dates?|availability|available|when)\b',message,re.I)
        and not re.search(r'\b(?:compare|cancel|reschedule|book|send|share|price|budget|bedrooms?|bathrooms?|also|then|instead|morning|afternoon|evening)\b',message,re.I))


def prepare_visit_choice(port, enabled):
    """Resolve a delivered, unexpired typed option before Hermes inference.

    A selected day reads availability. A selected hour creates only a draft
    recap. No booking, provider call, or new consent is authorized.
    """
    from datetime import datetime
    choice = port.choice or {}
    kind = choice.get('type')
    if (choice.get('status') != 'resolved' or kind not in {'visit_day','visit_time'}
            or _OTHER.search(port.message)
            or '?' in port.message
            or re.search(r"\b(?:instead|not|no|don.t|won.t|can.t|cannot|neither|rather|unless|if|maybe|or|another|different)\b",port.message,re.I)):
        return None
    menu = choice.get('menu') or {}
    picked = choice.get('choice') or {}
    prior = getattr(port,'prior_visit_offer',None) or {}
    if (menu.get('type') != kind or picked not in (menu.get('options') or [])
            or not prior.get('source_reply_message_id')
            or prior['source_reply_message_id'] != menu.get('source_reply_message_id')
            or prior.get('unit_id') != menu.get('unit_id')
            or prior.get('unit_id') != choice.get('unit_id')
            or menu.get('proposal_id') not in (None,prior.get('proposal_id'))
            or not prior.get('proposal_id')):
        return None
    if getattr(port,'explicit_focus',None) and port.explicit_focus.get('reference') != prior['unit_id']:
        return None
    try:
        expires = datetime.fromisoformat(prior['expires_at'])
        if expires.tzinfo is None or expires <= port.now:
            return None
    except (KeyError,TypeError,ValueError):
        return None
    if not any(x.get('date') == picked.get('date') and (kind == 'visit_day' or x.get('start_time') == picked.get('start_time'))
               for x in prior.get('options',[])):
        return None
    if kind == 'visit_day':
        tool = 'get_available_visit_slots'
        args = {'date_str':picked['date']}
    else:
        if picked.get('proposal_id') != prior['proposal_id']:
            return None
        tool = 'select_visit_time'
        args = {'proposal_id':prior['proposal_id'],'date_str':picked['date'],'start_time':picked['start_time']}
    if tool not in enabled:
        return None
    result = invoke_domain(port, tool, args)
    if not result.get('ok'):
        return None
    port.prepared_visit = {'kind':kind,'tool':tool,'args':deepcopy(args),'result':deepcopy(result)}
    return deepcopy(port.prepared_visit)


def replay_visit_choice(port, name, arguments):
    """Protect the exact pre-resolved choice from speculative SDK calls.

    Return None for ordinary tools; identical reads/drafts reuse the outcome.
    Never replay a booking or bypass the published tool allowlist.
    """
    prepared = getattr(port,'prepared_visit',None)
    if not prepared or name not in {'get_available_visit_slots','select_visit_time'}:
        return None
    args = dict(arguments)
    expected = prepared['args']
    if name == prepared['tool']:
        if (name == 'get_available_visit_slots' and set(args) <= {'date_str','time_preference'}
                and args.get('date_str') in (None,'',expected['date_str'])
                and args.get('time_preference') in (None,'any')) or (name == 'select_visit_time' and args == expected):
            return deepcopy(prepared['result'])
    return {'error':'Use the verified current visit selection; no further selection is authorized by this message.',
            'error_code':'VISIT_SELECTION_ALREADY_RESOLVED',
            'next_action':'Use verified_visit_selection in the server context. A day is not a time; a time is not booking consent.'}


def safe_visit_tools(port, observations):
    if not isinstance(observations,list):
        return False
    # Only the exact rejection generated by the cache boundary can be ignored,
    # and only when a verified native call already succeeded in this turn.
    prepared = getattr(port,'prepared_visit',None)
    filtered = [x for x in observations if not (prepared and isinstance(x,dict)
                and x.get('status') == 'rejected'
                and x.get('tool') in {'get_available_visit_slots','select_visit_time'}
                and x.get('error_code') == 'VISIT_SELECTION_ALREADY_RESOLVED')]
    return safe_tools(filtered, _VISITS)


def ensure_search(port, observations, enabled):
    """Recover a missing explicit search through the native read port once.

    Existing correct batches win. Never turn an unauthorized or incomplete
    read into evidence; leave mixed goals to Hermes.
    """
    if 'search_properties' not in enabled or not safe_tools(observations,_READS) or port.offered_media:
        return False
    criteria = explicit_search_filters(port.message)
    if not criteria or primary_declaration(port.message,port.state):
        return False
    if port.search_batches and port.search_batches[-1]['search'] == port.state.get('active_search') and exact_search(port.search_batches[-1],port.message,port.inbound_id):
        return True
    # Only use current actual input and approved domain; no new inference.
    # Don't rewrite a partial/truncated successful listing into another list.
    if port.search_batches:
        latest=port.search_batches[-1]
        if (set(latest['search'].get('criteria') or {}) - {'bedrooms','bedrooms_any','bedrooms_min','bedrooms_max','max_price_usd','relative_price_lt'}
                or latest['search'].get('match_count') != len(latest['rows'])):
            return False
    result=invoke_domain(port,'search_properties',{'scope':'temporary','criteria':criteria})
    return bool(result.get('ok') and port.search_batches and exact_search(port.search_batches[-1],port.message,port.inbound_id))
