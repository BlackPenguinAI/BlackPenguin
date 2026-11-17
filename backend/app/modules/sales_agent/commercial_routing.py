"""P1-B: classify already planned commercial tasks, without granting effects.

The label only selects a LangGraph observation node. Every node executes the
same scoped observation loop, with unchanged read/write permissions, budgets,
checks and persistence. A mixed/unknown state deliberately uses the legacy
observation path. No message text or model confidence is used for routing.
"""
from dataclasses import dataclass
from typing import Literal

VERSION = 'sales-commercial-routing/1.0'
KINDS = frozenset({'information', 'materials', 'appointments', 'clarification', 'mixed'})
BASES = {
    'information': 'current_scoped_information_tasks',
    'materials': 'current_scoped_material_tasks',
    'appointments': 'current_scoped_appointment_tasks',
    'clarification': 'current_unresolved_clarification',
    'mixed': 'mixed_or_unclassified_tasks',
}
INFORMATION = frozenset({'catalog', 'property_details', 'pricing', 'financing',
                         'inventory', 'location', 'delivery', 'amenities'})
CONTROLS = frozenset({'human', 'opt_out'})


@dataclass(frozen=True)
class ObservationDecision:
    kind: Literal['information', 'materials', 'appointments', 'clarification', 'mixed']
    basis: str


def _topic(value):
    name = getattr(value, 'value', value)
    return name if isinstance(name, str) else None


def classify(outcome, inbound_id, *, active=True):
    """Select a read-only observation domain from the persisted *current* turn.

    Classification is descriptive, not a capability. Never reads raw lead text,
    creates a tool candidate, changes task state, or authorizes a transaction.
    Historical and unknown tasks never provide affirmative routing evidence.
    """
    fallback = ObservationDecision('mixed', BASES['mixed'])
    if not active or not inbound_id or outcome is None:
        return fallback
    state = getattr(outcome, 'state', None)
    understanding = getattr(state, 'last_understanding', None)
    tasks = getattr(state, 'tasks', None)
    if understanding is None or tasks is None:
        return fallback
    if getattr(outcome, 'results', ()):  # Legacy/planner results must not be reclassified.
        return fallback
    plan = getattr(outcome, 'plan', None) or {}
    if plan.get('deferred_requests'):
        return fallback
    current = [task for task in tasks
               if getattr(task, 'source_message_id', None) == inbound_id
               and getattr(task, 'status', None) != 'cancelled']
    topics = {_topic(getattr(task, 'topic', None)) for task in current}
    requested = {_topic(getattr(request, 'topic', None)) for request in understanding.requests
                 if getattr(request, 'polarity', None) == 'request'}
    if (not requested or not topics or None in requested or None in topics
            or not requested.issubset(topics)
            or any(getattr(request, 'polarity', None) != 'request' for request in understanding.requests)):
        return fallback
    if any(getattr(understanding, key, None) for key in (
            'constraints', 'releases', 'alternatives', 'cancellation', 'reschedule',
            'wait', 'moderation', 'comparison', 'personal_facts',
            'preference_withdrawals', 'source_purposes', 'objections')):
        return fallback
    if any(getattr(task, 'alternative_group', None) for task in current):
        return fallback
    unresolved = bool(getattr(understanding, 'requires_clarification', False)
                      or (plan.get('questions') or [])
                      or any(getattr(task, 'binding_status', None) == 'unresolved'
                             or getattr(task, 'status', None) == 'awaiting_user'
                             for task in current))
    if unresolved:
        # Do not claim a specialized read for a mixed or unresolved operation.
        return (ObservationDecision('clarification', BASES['clarification'])
                if topics == requested and topics.issubset(INFORMATION | {'materials', 'appointment'})
                else fallback)
    if topics != requested:  # Retained unrelated tasks => conservative generic path.
        return fallback
    if topics == {'materials'} and not any(getattr(understanding, k, None)
                                          for k in ('visit', 'appointment_query')):
        return ObservationDecision('materials', BASES['materials'])
    if topics.issubset(INFORMATION) and not any(getattr(understanding, k, None)
                                                for k in ('visit', 'appointment_query')):
        return ObservationDecision('information', BASES['information'])
    if topics == {'appointment'} and (
            getattr(understanding, 'visit', None)
            or getattr(understanding, 'appointment_query', None)):
        return ObservationDecision('appointments', BASES['appointments'])
    # A human handoff plus pricing, any unrecognized topic, and all composite
    # operations keep the proven shared loop without dropping a request.
    return fallback
