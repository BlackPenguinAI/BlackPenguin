"""P02/P03 offline preparation of a Hermes turn from existing BlackPenguin rows.

DO NOT CALL from the current live inbound worker: the production conversation
routing, tool-effect receipts and isolated worker deployment arrive in P04+.
This module has no FastAPI route and does not commit to the database.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .bp_context import build_bp_snapshot, require_scoped_entities
from .bp_read_port import BlackPenguinReadPort
from .bp_state_store import LoadedState, load
from .config import HermesSettings
from .contracts import TurnRequest, TurnResult, TurnScope
from .runtime import HermesSalesRuntime
from .choice_state import resolve_visible_choice


@dataclass(frozen=True)
class PreparedHermesTurn:
    scope: TurnScope
    inbound_message_id: str
    expected_revision: int
    result: TurnResult
    proposed_state: dict[str, Any]
    # Preparation alone does NOT authorize an outbound message or commit state.
    effects_executed: int = 0
    persisted: bool = False


def _approved_history(db, scope: TurnScope, inbound):
    from app.modules.sales_agent.models import SalesMessage
    rows = db.query(SalesMessage).filter(
        SalesMessage.conversation_id == scope.conversation_id,
        SalesMessage.created_at <= inbound.created_at,
        SalesMessage.role.in_(['user','assistant']),
    ).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).limit(30).all()
    messages = []
    for row in reversed(rows):
        if row.id == inbound.id:
            continue
        if (row.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
            continue
        if row.direction == 'outbound' and row.status not in ('sent','delivered','accepted'):
            continue
        # Preserve actual public dialogue, not model tool calls, drafts or
        # reserialized state that could be mistaken for something the lead said.
        messages.append({'role': 'user' if row.direction == 'inbound' else 'assistant',
                         'content': row.content[:4000]})
    return messages[-25:]


def prepare_offline_turn(db, scope: TurnScope, *, inbound_message_id: str,
                         settings: HermesSettings) -> PreparedHermesTurn:
    """Read-only preparation for deterministic integration testing.

    SDK/model invocation is synchronous (as in P01) and can take time; a future
    isolated worker must not hold a production DB connection during inference.
    No state writes, CRM writes, calendar calls, asset URLs or provider sends.
    """
    _, _, lead, conversation = require_scoped_entities(db, scope)
    if conversation.channel != 'simulation':
        raise PermissionError('P02 prepares simulation turns only; live channels activate in P04')
    from app.modules.sales_agent.models import SalesMessage
    inbound = db.query(SalesMessage).filter(
        SalesMessage.id == inbound_message_id,
        SalesMessage.conversation_id == scope.conversation_id,
        SalesMessage.direction == 'inbound', SalesMessage.role == 'user',
    ).one_or_none()
    if not inbound or (inbound.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
        raise PermissionError('Hermes turn must originate from a persisted, scoped inbound message')
    with db.no_autoflush:
        snapshot = build_bp_snapshot(db, scope, channel=conversation.channel)
        loaded: LoadedState = load(db, scope)
        history = _approved_history(db, scope, inbound)
    working = deepcopy(loaded.data)
    working['_active_source_message_id'] = inbound.id  # never persisted
    choice = resolve_visible_choice(working, inbound.content)
    context = snapshot.for_hermes()
    context.update({
        'conversation_focus': deepcopy(working.get('conversation_focus')),
        'primary_preferences': deepcopy(working.get('search_preferences')),
        'property_filters': deepcopy(working.get('property_filters')),
        'visit_draft': deepcopy(working.get('visit_draft')),
        'last_presented_units': deepcopy(working.get('last_presented_units')),
        'last_presented_choice_set': deepcopy(working.get('last_presented_choice_set')),
        'resolved_visible_choice': deepcopy(choice),
        'state_revision': loaded.revision,
    })
    port = BlackPenguinReadPort(snapshot, state=working, buyer_message=inbound.content,
                                enable_preference_drafts=True)
    result = HermesSalesRuntime(settings, port, state_draft_tools=frozenset(
        {'update_search_preferences'})).process_turn(TurnRequest(
            scope=scope, message=inbound.content, history=history,
            channel=conversation.channel, verified_context=context,
        ))
    # Strip non-durable turn-local flags. The next delivery/transaction stage
    # (P04) is responsible for validating and saving state atomically with a
    # verified outbound receipt; this prepare method never calls save().
    working.pop('_active_source_message_id', None)
    return PreparedHermesTurn(scope=scope, inbound_message_id=inbound.id,
                              expected_revision=loaded.revision, result=result,
                              proposed_state=working)


def commit_simulation_receipt(db, prepared: PreparedHermesTurn, *,
                              outbound_message_id: str) -> LoadedState:
    """P03 opt-in simulation state receipt AFTER durable in-app assistant output.

    Reject mismatched text, unsent output, live conversations and foreign leads.
    The caller must commit the surrounding DB transaction. This method never
    dispatches the message, and cannot be used for real provider delivery.
    """
    from app.modules.sales_agent.models import SalesMessage
    from .bp_state_store import save

    _, _, _, conversation = require_scoped_entities(db, prepared.scope)
    if conversation.channel != 'simulation':
        raise PermissionError('P03 state receipts are simulation-only')
    inbound = db.query(SalesMessage).filter(
        SalesMessage.id == prepared.inbound_message_id,
        SalesMessage.conversation_id == prepared.scope.conversation_id,
        SalesMessage.direction == 'inbound', SalesMessage.role == 'user',
    ).one_or_none()
    outbound = db.query(SalesMessage).filter(
        SalesMessage.id == outbound_message_id,
        SalesMessage.conversation_id == prepared.scope.conversation_id,
        SalesMessage.direction == 'outbound', SalesMessage.role == 'assistant',
        SalesMessage.channel == 'simulation', SalesMessage.status == 'sent',
    ).one_or_none()
    if (inbound is None or outbound is None
            or (inbound.metadata_json or {}).get('lead_id', prepared.scope.lead_id) != prepared.scope.lead_id
            or (outbound.metadata_json or {}).get('lead_id', prepared.scope.lead_id) != prepared.scope.lead_id
            or (outbound.metadata_json or {}).get('hermes_inbound_message_id') != prepared.inbound_message_id
            or (outbound.metadata_json or {}).get('engine') != 'hermes-agent'
            or outbound.content != prepared.result.reply):
        raise PermissionError('Only the exact delivered simulation reply may commit Hermes state')
    state = deepcopy(prepared.proposed_state)
    state['last_assistant_reply'] = outbound.content
    # P04 will persist a new *typed*, backend-verified menu when its delivery
    # receipt confirms that the numbered choices were actually sent. For now
    # do not infer selection authority from arbitrary model-generated prose.
    state['last_presented_choice_set'] = None
    state['choice_set_initialized'] = True
    return save(db, prepared.scope, expected_revision=prepared.expected_revision,
                event_key='hermes:sim:' + prepared.inbound_message_id,
                state=state, event_type='simulation_receipt')
