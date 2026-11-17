"""Deterministic preview of a delivered, unambiguous booking acceptance.

The actual first_booking.handle still checks scope, proposal hash, expiry,
consent, active meetings, seller, availability and transactional idempotency.
This module only avoids a redundant LLM reinterpretation of plain acceptance.
"""
from datetime import datetime, timezone

VERSION = 'backend-booking-acceptance/1.0'
COMPETING = frozenset({
    'material_offer', 'release_offer', 'appointment_offer', 'location_offer',
    'reschedule_confirmation', 'reschedule_meeting_offer', 'reschedule_offer',
    'cancellation_confirmation', 'cancellation_meeting_offer',
    'control_confirmation', 'wait_offer',
})


def qualifies(*, plain_assent, proposal, metadata, scope, accepted, now,
              digest_fn, action_holds=()):
    """Pure authorization preflight; failure always falls back to LLM.

    A preflight success is NOT permission to book. It only permits creating a
    typed interpretation of the customer's exact accepted summary.
    """
    if not plain_assent or not accepted or 'appointment' in action_holds:
        return False
    if any(metadata.get(key) for key in COMPETING):
        return False
    offer = metadata.get('booking_confirmation') or {}
    if not isinstance(proposal, dict) or not isinstance(offer, dict):
        return False
    required = {'id', 'scope', 'context', 'preferences', 'option', 'expires_at'}
    if not required.issubset(proposal) or not offer.get('id'):
        return False
    if (proposal['scope'] != scope or offer['id'] != proposal['id'] or
        proposal['id'] != digest_fn({k: v for k, v in proposal.items() if k != 'id'})):
        return False
    try:
        expiry = datetime.fromisoformat(proposal['expires_at'])
        clock = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if expiry.tzinfo is None or expiry <= clock:
            return False
        # Do not accept stale or conflicting offer metadata.
        if offer.get('expires_at') and datetime.fromisoformat(offer['expires_at']) <= clock:
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def try_preview(db, scope, conversation, inbound, *, state, previous_meta,
                expected_revision, event_key, action_holds=()):
    """Save an accepted preview without calling a model when explicitly safe.

    Uses the ordinary dialogue event/revision machinery, so planning and
    delivery retain the same contract as model-produced interpretations.
    """
    from .first_booking import _plain_summary_assent, accepted_outbound
    from .turn_configuration import digest
    from .execution import now as workflow_now
    offer_message = accepted_outbound(db, conversation, 'booking_confirmation')
    if not offer_message:
        return None
    actual_meta = offer_message.metadata_json or {}
    # A stale previous_meta must not authorize a non-current offer.
    if previous_meta.get('booking_confirmation') != actual_meta.get('booking_confirmation'):
        return None
    if not qualifies(plain_assent=_plain_summary_assent(inbound.content),
                    proposal=state.booking_proposal, metadata=actual_meta,
                    scope=scope.__dict__, accepted=True, now=workflow_now(datetime),
                    digest_fn=digest, action_holds=action_holds):
        return None

    from .understanding_contract import Understanding
    from .dialogue_store import save
    from .understanding_service import PreviewOutcome
    current = inbound.content
    understanding = Understanding.model_validate({
        'version': 'sales-understanding/1.0',
        'requests': [{'id': 'confirmed_current_booking', 'topic': 'appointment',
                      'polarity': 'request', 'evidence': current}],
        'all_of': ['confirmed_current_booking'], 'alternatives': [],
        'constraints': [], 'references': [], 'preferences': [],
        'visit': {'action': 'confirm', 'evidence': current, 'timing': None},
        'requires_clarification': False, 'clarification_question': None,
        'confidence': 1.0,
    }).check_evidence(current)
    prepared = state.model_copy(deep=True, update={'last_understanding': understanding})
    revision, saved_state = save(db, scope, event_key=event_key,
                                 expected_revision=expected_revision,
                                 state=prepared, kind='understanding_preview',
                                 metadata={
                                     'model': 'deterministic-booking-acceptance',
                                     'prompt_snapshot': {},
                                     'prompt_configuration_id': None,
                                     'inbound_message_id': inbound.id,
                                     'expected_revision': expected_revision,
                                     'outcome': 'accepted', 'error_code': None,
                                     'input_contract': VERSION,
                                     'interpretation_attempts': [],
                                     'validated_declarations': [],
                                     'decision': 'verified_current_booking_confirmation',
                                 })
    return PreviewOutcome(revision, saved_state, 'accepted', ())
