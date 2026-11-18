"""Exact current-offer continuations: interpret an invitation, never book a visit.

This module is deliberately narrower than an intent classifier. It accepts only
an affirmative reply to the last delivered visit invitation, or a repeated
property name matching an outstanding backend-generated visit-time offer.
It changes only interpretation; the ordinary reader, transaction and consent
checks still own appointment availability and booking.
"""
import re
from datetime import datetime, timezone

VERSION = 'sales-live-visit-continuity/1.0'
COMPETING = ('material_offer', 'release_offer', 'booking_confirmation',
             'control_confirmation', 'location_offer', 'reschedule_confirmation',
             'cancellation_confirmation', 'wait_offer')


def _normalize_name(text):
    return re.sub(r'\s+', ' ', re.sub(r'[.!?]+$', '', text.strip())).casefold()


def classify(text, previous_meta, state, *, action_holds=(), now=None):
    """Returns a *read-only* continuation kind, never booking authorization."""
    if not text or len(text) > 300 or 'appointment' in action_holds:
        return None
    if any(previous_meta.get(k) for k in COMPETING):
        return None
    selected = getattr(state, 'selected_property_type_id', None)
    if not selected:
        return None
    constraints = [*(getattr(state, 'constraints', ()) or ()),
                   *(getattr(state, 'property_constraints', ()) or ())]
    if any(getattr(getattr(c, 'topic', None), 'value', None) == 'appointment'
           for c in constraints):
        return None
    plain_yes = bool(re.fullmatch(r'\s*(?:yes(?: please)?|sure|ok(?:ay)?|please do)[.!]?\s*',
                                  text, flags=re.I))
    if plain_yes and previous_meta.get('visit_invitation') and not previous_meta.get('appointment_offer'):
        # A single focused current property is required; this prepares only a
        # fresh search, not an existing option selection or a booking.
        return 'accepted_visit_invitation'
    offer = previous_meta.get('appointment_offer')
    if not isinstance(offer, dict) or not offer.get('options'):
        return None
    context = offer.get('context') or {}
    name = context.get('property_type_name')
    if not name or context.get('property_type_id') != selected:
        return None
    if _normalize_name(text) != _normalize_name(name):
        return None
    try:
        expiry = datetime.fromisoformat(offer['expires_at'])
        clock = now or datetime.now(timezone.utc)
        if expiry.tzinfo is None or expiry <= clock:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return 'reaffirmed_offered_property'


def try_preview(db, scope, conversation, inbound, *, state, previous_meta,
                expected_revision, event_key, action_holds=()):
    from .first_booking import accepted_outbound
    from .execution import now as workflow_now
    current = inbound.content
    kind = classify(current, previous_meta, state, action_holds=action_holds,
                    now=workflow_now(datetime))
    if not kind:
        return None
    offer_key = 'visit_invitation' if kind == 'accepted_visit_invitation' else 'appointment_offer'
    previous = accepted_outbound(db, conversation, offer_key)
    if not previous or (previous.metadata_json or {}).get(offer_key) != previous_meta.get(offer_key):
        return None
    from .understanding_contract import Understanding
    from .dialogue_store import save
    from .understanding_service import PreviewOutcome
    understood = Understanding.model_validate({
        'version':'sales-understanding/1.0',
        'requests':[{'id':'scoped_visit_continuation','topic':'appointment',
                     'polarity':'request','evidence':current}],
        'all_of':['scoped_visit_continuation'], 'alternatives':[],
        'constraints':[], 'references':[], 'preferences':[],
        'visit':{'action':'request','evidence':current,'timing':None},
        'requires_clarification':False, 'clarification_question':None,
        'confidence':1.0,
    }).check_evidence(current)
    prepared = state.model_copy(deep=True, update={'last_understanding':understood})
    if kind == 'accepted_visit_invitation':
        # An invitation is a new request; do not silently inherit a stale
        # date/time or proposal from a previously declined visit.
        prepared.booking_search = {}
        prepared.booking_proposal = None
    revision, saved = save(db, scope, event_key=event_key,
                           expected_revision=expected_revision, state=prepared,
                           kind='understanding_preview', metadata={
        'model':'deterministic-visit-context','inference_mode':'deterministic',
        'prompt_snapshot':{'version':VERSION,'model_invoked':False,'system':None},
        'prompt_configuration_id':None,'inbound_message_id':inbound.id,
        'expected_revision':expected_revision,'outcome':'accepted',
        'error_code':None,'input_contract':VERSION,'interpretation_attempts':[],
        'validated_declarations':[], 'decision':kind,
        'effect_authorization':False,
    })
    return PreviewOutcome(revision, saved, 'accepted', ())
