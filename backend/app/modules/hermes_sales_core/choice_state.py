"""Non-persistent, reusable P01 choice-set ledger; BP persistence arrives in P03.

Only delivered assistant messages create active menus. Raw LLM tool results never
become selectable by themselves. This mirrors Hermes v13.3.3's contract.
"""
from __future__ import annotations
from copy import deepcopy
from . import contextual_choices


def record_delivered_menu(state: dict, *, menu: dict, outbound_message_id: str) -> dict:
    if not isinstance(outbound_message_id, str) or not outbound_message_id.strip():
        raise ValueError('An actual outbound message ID is required')
    if len(menu.get('options') or []) < 2:
        raise ValueError('A selectable menu requires at least two actual options')
    recorded = contextual_choices.menu_record(menu, reply_message_id=outbound_message_id)
    state['last_presented_choice_set'] = deepcopy(recorded)
    state['choice_set_initialized'] = True
    return recorded


def resolve_visible_choice(state: dict, buyer_message: str) -> dict | None:
    return contextual_choices.resolve(state, buyer_message)


def clear_visible_choice(state: dict) -> None:
    state['last_presented_choice_set'] = None
    state['choice_set_initialized'] = True
