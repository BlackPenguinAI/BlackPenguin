"""P04 opt-in Hermes simulation integration with *delivered* action receipts.

No FastAPI route, no SMS/WhatsApp dispatch, no live booking. Do not invoke
from the production sales worker. Model calls only prepare draft proposals;
the separately authorized P04 executor commits simulation actions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import re

from .bp_context import build_bp_snapshot, require_scoped_entities
from .bp_operational_port import BPOperationalDraftPort, P04_TOOL_NAMES
from .bp_operation_receipts import recap_visible, visible_menu
from .bp_state_store import LoadedState, load
from .bp_turn import PreparedHermesTurn, _approved_history, commit_simulation_receipt
from .choice_state import record_delivered_menu, resolve_visible_choice
from .config import HermesSettings
from .contracts import TurnRequest, TurnScope
from .runtime import HermesSalesRuntime


@dataclass(frozen=True)
class P04PreparedTurn:
    prepared: PreparedHermesTurn
    proposed_menus: list[dict]


def prepare_p04_simulation_turn(db, scope: TurnScope, *, inbound_message_id: str,
                                settings: HermesSettings, now=None,
                                port_factory=BPOperationalDraftPort) -> P04PreparedTurn:
    """Explicit test/simulation entrypoint, not wired to the live worker."""
    _, _, _, conversation = require_scoped_entities(db, scope)
    if conversation.channel != 'simulation':
        raise PermissionError('P04 simulation preparation is never allowed on live channels')
    from app.modules.sales_agent.models import SalesMessage
    inbound = db.query(SalesMessage).filter_by(
        id=inbound_message_id, conversation_id=scope.conversation_id,
        direction='inbound', role='user',
    ).one_or_none()
    if not inbound or (inbound.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
        raise PermissionError('An authenticated, persisted lead inbound is required')
    with db.no_autoflush:
        snapshot = build_bp_snapshot(db, scope, channel='simulation')
        loaded = load(db, scope)
        history = _approved_history(db, scope, inbound)
    working = deepcopy(loaded.data)
    working['_active_source_message_id'] = inbound.id
    selection = resolve_visible_choice(working, inbound.content)
    context = snapshot.for_hermes()
    context.update({
        'conversation_focus': deepcopy(working.get('conversation_focus')),
        'primary_preferences': deepcopy(working.get('search_preferences')),
        'property_filters': deepcopy(working.get('property_filters')),
        'visit_draft': deepcopy(working.get('visit_draft')),
        'last_slot_search': deepcopy(working.get('last_slot_search')),
        'confirmation_request': deepcopy(working.get('confirmation_request')),
        'resolved_visible_choice': deepcopy(selection),
        'state_revision': loaded.revision,
    })
    port = port_factory(db, snapshot, state=working, buyer_message=inbound.content,
                        inbound_message_id=inbound.id, now=now)
    result = HermesSalesRuntime(
        settings, port,
        state_draft_tools=frozenset({'update_search_preferences'}),
        operational_draft_tools=P04_TOOL_NAMES,
    ).process_turn(TurnRequest(scope=scope, message=inbound.content,
                               history=history, verified_context=context,
                               channel='simulation'))
    working.pop('_active_source_message_id', None)
    return P04PreparedTurn(
        prepared=PreparedHermesTurn(scope=scope, inbound_message_id=inbound.id,
                                    expected_revision=loaded.revision, result=result,
                                    proposed_state=working),
        proposed_menus=deepcopy(port.menus),
    )




def commit_p04_simulation_receipt(db, turn: P04PreparedTurn, *,
                                  outbound_message_id: str) -> LoadedState:
    """Commit a P04 state draft only after exact, durable in-app delivery.

    Does not execute external actions. The state remains tied to the real
    outbound text and its lead/message ID. Caller owns db.commit/rollback.
    """
    from app.modules.sales_agent.models import SalesMessage
    prepared = turn.prepared
    outbound = db.query(SalesMessage).filter_by(
        id=outbound_message_id, conversation_id=prepared.scope.conversation_id,
        direction='outbound', role='assistant', channel='simulation',
        status='sent',
    ).one_or_none()
    if (not outbound or outbound.content != prepared.result.reply or
            (outbound.metadata_json or {}).get('lead_id',prepared.scope.lead_id)!=prepared.scope.lead_id or
            (outbound.metadata_json or {}).get('hermes_inbound_message_id')!=prepared.inbound_message_id or
            (outbound.metadata_json or {}).get('engine')!='hermes-agent'):
        raise PermissionError('The P04 response was not durably delivered to the scoped lead')
    state = deepcopy(prepared.proposed_state)
    state['last_presented_choice_set'] = None
    state['choice_set_initialized'] = True
    offered = state.get('last_slot_search')
    if isinstance(offered,dict) and offered.get('source_inbound_message_id') == prepared.inbound_message_id:
        # Only the last actual tool menu that matches that exact offer may
        # become selectable. Do not persist hidden tool results as options.
        for menu in reversed(turn.proposed_menus):
            if (menu.get('proposal_id') not in (None, offered['proposal_id']) or
                    menu.get('unit_id') != offered['unit_id']):
                continue
            if visible_menu(outbound.content, menu):
                state['last_presented_choice_set']=record_delivered_menu(
                    state, menu=menu, outbound_message_id=outbound.id)
                offered['source_reply_message_id']=outbound.id
                break
    proposal = state.get('confirmation_request')
    if (isinstance(proposal,dict) and proposal.get('status')=='recap_required' and
            proposal.get('selected_inbound_message_id')==prepared.inbound_message_id and
            recap_visible(outbound.content,proposal)):
        proposal['status']='awaiting_confirmation'
        proposal['recap_message_id']=outbound.id
    # The executor is separate. A tool response saying "pending" is never
    # converted to "booked", "cancelled" or "shared" here.
    return commit_simulation_receipt(
        db, replace(prepared,proposed_state=state),outbound_message_id=outbound.id)
