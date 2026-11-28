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
    minimum = 1 if menu.get('type') in {'visit_day','visit_time'} and menu.get('display_name') else 2
    if len(menu.get('options') or []) < minimum:
        raise ValueError('A selectable menu requires actual options')
    recorded = contextual_choices.menu_record(menu, reply_message_id=outbound_message_id)
    # Live delivery already verified this scoped commercial label against the
    # actual text. Preserve it for the next turn's identical visible_menu proof.
    # The internal unit_id remains the only identifier used for operations.
    if menu.get('type') in {'visit_day', 'visit_time'} and 'display_name' in menu:
        from .commercial_delivery import clean_label
        if not clean_label(menu['display_name']):
            raise ValueError('Invalid verified visit display name')
        recorded['display_name'] = menu['display_name']
    state['last_presented_choice_set'] = deepcopy(recorded)
    state['choice_set_initialized'] = True
    return recorded


def resolve_visible_choice(state: dict, buyer_message: str) -> dict | None:
    return contextual_choices.resolve(state, buyer_message)


def clear_visible_choice(state: dict) -> None:
    state['last_presented_choice_set'] = None
    state['choice_set_initialized'] = True
