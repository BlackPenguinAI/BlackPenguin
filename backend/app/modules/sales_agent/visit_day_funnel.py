"""P3-B: audited day offers for a first property visit.

A day choice is a request to LOOK UP slots, not appointment consent.  Only a
current, delivered, scope-bound day offer may be interpreted deterministically.
All eligible dates come from the existing appointment availability engine.
"""
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

VERSION = 'sales-visit-day-funnel/1.0'


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def spread_slots(slots):
    """Choose early/middle/late real starts, not the first three adjacent starts.

    This selects among already verified starts; it never manufactures slots.
    """
    if len(slots) <= 3:
        return list(slots)
    middle = len(slots) // 2
    return [slots[i] for i in (0, middle, len(slots) - 1)]


def short_choice(text):
    """Bounded ordinal or explicit day/date only; reject combined requests."""
    from .turn_context import choice_index
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 90:
        return None
    value = text.strip().rstrip('.!?').strip()
    index = choice_index(value)
    if index is None:
        match = re.fullmatch(r'(?:(?:the|la|el)\s+)?(first|second|third)\s+one', value, re.I)
        if match:
            index = {'first': 0, 'second': 1, 'third': 2}[match.group(1).casefold()]
    return ('index', index) if index is not None else ('date_label', value)


def choose(text, offer, selected_property_id, *, now=None):
    """Resolve a day from an immutable offered order, never a free date guess."""
    if not isinstance(offer, dict) or offer.get('version') != VERSION:
        return None
    if not selected_property_id or offer.get('property_type_id') != selected_property_id:
        return None
    days = offer.get('days')
    if not isinstance(days, list) or not 1 <= len(days) <= 3:
        return None
    if any(not isinstance(item, dict) or set(item) != {'date', 'label'} or
           not isinstance(item.get('date'), str) or not isinstance(item.get('label'), str)
           for item in days):
        return None
    dates = [item['date'] for item in days]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        return None
    try:
        expiry = datetime.fromisoformat(offer['expires_at'])
        clock = _utc(now or datetime.now(timezone.utc))
        ZoneInfo(offer['timezone'])
        if expiry.tzinfo is None or expiry <= clock:
            return None
        # Do not revive a previously offered day after midnight in project time.
        local_today = clock.astimezone(ZoneInfo(offer['timezone'])).date()
        from datetime import date
        if any(date.fromisoformat(value) < local_today for value in dates):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    parsed = short_choice(text)
    if not parsed:
        return None
    kind, token = parsed
    if kind == 'index':
        return dates[token] if 0 <= token < len(dates) else None
    text_norm = re.sub(r'\s+', ' ', token.casefold()).strip()
    # Only exact labels printed in this offer, or an unambiguous weekday/date.
    matches = [item['date'] for item in days if text_norm in {
        item['label'].casefold(),
        datetime.fromisoformat(item['date']).strftime('%A').casefold(),
        f"{datetime.fromisoformat(item['date']):%B} {datetime.fromisoformat(item['date']).day}".casefold(),
        item['date'].casefold(),
    }]
    return matches[0] if len(matches) == 1 else None


def day_labels(dates):
    """Deterministic English labels; no speculative availability statements."""
    return [{'date': value, 'label':
             f"{datetime.fromisoformat(value):%A}, {datetime.fromisoformat(value):%B} {datetime.fromisoformat(value).day}"}
            for value in dates]


def message(property_name, days, timezone_name):
    """A verified day list, always naming the scoped active property."""
    labels = '\n'.join(f"{index}. {entry['label']}" for index, entry in enumerate(days, 1))
    city = timezone_name.rsplit('/', 1)[-1].replace('_', ' ')
    return (f"For {property_name}, I found visit availability on these days "
            f"({city} local time):\n\n{labels}\n\n"
            f"Which day works best for your visit to {property_name}?")


def try_preview(db, scope, conversation, inbound, *, state, previous_meta,
                expected_revision, event_key, action_holds=()):
    """An exact current day selection becomes a *read-only* visit request."""
    if 'appointment' in action_holds or any(previous_meta.get(key) for key in (
            'appointment_offer', 'booking_confirmation', 'material_offer',
            'control_confirmation', 'location_offer', 'release_offer',
            'reschedule_confirmation', 'cancellation_confirmation')):
        return None
    from .first_booking import accepted_outbound
    previous = accepted_outbound(db, conversation, 'visit_day_offer')
    if not previous:
        return None
    offer = (previous.metadata_json or {}).get('visit_day_offer')
    if offer != previous_meta.get('visit_day_offer'):
        return None
    from .execution import now as workflow_now
    # A one-type project can have an unambiguous visit focus even when the
    # lead never explicitly selected a catalog item. Booking-search focus is
    # still scoped to this lead/project and must match any active selection.
    focus = (state.booking_search or {}).get('property_type_id')
    if not focus or (state.selected_property_type_id and focus != state.selected_property_type_id):
        return None
    if offer.get('unit_id') != (state.booking_search or {}).get('unit_id'):
        return None
    chosen = choose(inbound.content, offer, focus, now=workflow_now(datetime))
    if chosen is None:
        return None
    if any(getattr(getattr(c, 'topic', None), 'value', None) == 'appointment'
           for c in [*state.constraints, *state.property_constraints]):
        return None
    from .understanding_contract import Understanding
    from .dialogue_store import save
    from .understanding_service import PreviewOutcome
    content = dict(version='sales-understanding/1.0',
                   requests=[dict(id='p3b_day', topic='appointment', polarity='request',
                                  evidence=inbound.content)],
                   all_of=['p3b_day'], alternatives=[], constraints=[],
                   references=[], preferences=[],
                   visit={'action':'request', 'evidence':inbound.content, 'timing':None},
                   requires_clarification=False, clarification_question=None, confidence=1.0)
    understood = Understanding.model_validate(content).check_evidence(inbound.content)
    prepared = state.model_copy(deep=True, update={'last_understanding':understood})
    prepared.booking_search = {**state.booking_search,
                               'date_from': chosen, 'date_until': chosen,
                               'day_offer_selection_message_id': inbound.id}
    prepared.booking_proposal = None
    revision, saved = save(db, scope, event_key=event_key,
                           expected_revision=expected_revision, state=prepared,
                           kind='understanding_preview', metadata={
        'model':'deterministic-visit-day', 'inference_mode':'deterministic',
        'prompt_snapshot':{'version':VERSION, 'model_invoked':False, 'system':None},
        'prompt_configuration_id':None, 'inbound_message_id':inbound.id,
        'expected_revision':expected_revision, 'outcome':'accepted',
        'error_code':None, 'input_contract':VERSION,
        'interpretation_attempts':[], 'validated_declarations':[],
        'selected_visit_day':chosen, 'effect_authorization':False})
    return PreviewOutcome(revision, saved, 'accepted', ())
