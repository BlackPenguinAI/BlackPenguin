"""P1-B.2: bounded, read-only observation profiles over validated current tasks.

These profiles may reduce READ capacity and redundant observation-model calls.
They cannot authorize a tool, change tasks, change the graph route, or bypass
ReadTools' per-call scope/policy checks. Unrecognized contexts use legacy limits.
"""
from dataclasses import dataclass
from .commercial_routing import INFORMATION

VERSION = 'sales-observation-budget/1.0'
SPECIALIZED = frozenset({'information', 'materials', 'appointments'})


@dataclass(frozen=True)
class ReadBudget:
    requested_kind: str
    effective_kind: str
    max_reads: int
    legacy_max_reads: int
    single_pass_information: bool


def _cap(plan):
    limits = (plan or {}).get('limits') or {}
    # This is exactly the original observation_loop read ceiling.
    return min(6, limits.get('steps', 8), limits.get('read_units', 12) // 2)


def for_turn(requested_kind, current_tasks, plan, understanding):
    """Cap a specialist only when all current non-cancelled tasks fit its domain.

    Materials can require one original read and one discovery-only fallback per
    current task. Appointments may require a task read plus availability. All
    mixed, unresolved and unknown cases retain the original ceiling.
    """
    baseline = _cap(plan)
    effective = 'mixed'
    active = [t for t in current_tasks if getattr(t, 'status', None) != 'cancelled']
    topics = {getattr(getattr(t, 'topic', None), 'value', None) for t in active}
    if (requested_kind in SPECIALIZED and active and None not in topics
            and not any(getattr(t, 'alternative_group', None) for t in active)
            and not any(getattr(understanding, key, None) for key in
                        ('constraints', 'releases', 'alternatives', 'comparison',
                         'cancellation', 'reschedule', 'wait', 'moderation'))):
        if requested_kind == 'information' and topics.issubset(INFORMATION):
            effective = 'information'
            ceiling = len(active)  # A validated information task has one read ID.
        elif requested_kind == 'materials' and topics == {'materials'}:
            effective = 'materials'
            ceiling = 2 * len(active)  # Includes the bounded discovery-only read.
        elif requested_kind == 'appointments' and topics == {'appointment'}:
            effective = 'appointments'
            ceiling = 2 * len(active)  # Query plus visit-availability read.
    if effective == 'mixed':
        ceiling = baseline
    # A lower profile limit cannot increase any original budget.
    return ReadBudget(str(requested_kind), effective, min(baseline, ceiling), baseline,
                      effective == 'information')


def complete_information_batch(profile, *, rounds, current_tasks, available_tools,
                               decisions, results, understanding):
    """Skip a redundant *second* LLM decision, never skip a read or composition.

    The first model decision must have requested authorized reads, every current
    positive task must have completed, and there must be no remaining read,
    alternate, action, unresolved or policy uncertainty. Mixed/booking/material
    turns always keep the model loop unchanged. The composer still runs normally.
    """
    if not profile.single_pass_information or rounds != 1 or available_tools:
        return False
    if len(decisions) != 1 or decisions[0].get('status') != 'accepted' or decisions[0].get('action') != 'read':
        return False
    if not results or any(getattr(r, 'status', None) not in {'success', 'partial'} for r in results):
        return False
    active = [t for t in current_tasks if getattr(t, 'status', None) != 'cancelled']
    if not active or any(getattr(t, 'status', None) != 'completed' for t in active):
        return False
    if (getattr(understanding, 'requires_clarification', False)
            or any(getattr(understanding, key, None) for key in
                   ('visit', 'appointment_query', 'comparison', 'constraints',
                    'releases', 'alternatives', 'cancellation', 'reschedule',
                    'wait', 'moderation'))):
        return False
    return True
