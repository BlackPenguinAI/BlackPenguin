"""HEI-01A: explicit global Sales routing, independent of prompt policy.

This release has no production Hermes handler. Do not replace the gate with an
operator-controlled environment variable or infer readiness from P05.enabled.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

LANGGRAPH = 'langgraph'
HERMES = 'hermes'
TARGET_DEFAULT = HERMES
SELECTION_KEY = 'active_sales_engine'
ENGINES = frozenset({LANGGRAPH, HERMES})


class EngineSelectionError(ValueError):
    pass


class EngineUnavailable(RuntimeError):
    pass


def live_hermes_ready() -> bool:
    # HEI-01B/03/06 must supply a certified executable production route.
    # P08 simulation, enabled policy or a configured model are NOT readiness.
    return False


def read_engine(raw: dict | None) -> str:
    """Pre-HEI records have no selector; preserve the existing live engine."""
    if raw is None:
        return LANGGRAPH
    if not isinstance(raw, dict):
        raise EngineSelectionError('Invalid global sales routing configuration.')
    value = raw.get(SELECTION_KEY, LANGGRAPH)
    if not isinstance(value, str) or value not in ENGINES:
        raise EngineSelectionError('Invalid active sales engine; staff review required.')
    return value


def prompt_policy(raw: dict) -> dict:
    """Routing metadata is not an editable prompt setting."""
    result = deepcopy(raw)
    result.pop(SELECTION_KEY, None)
    return result


def routing_status(raw: dict | None) -> dict[str, Any]:
    ready = live_hermes_ready()
    try:
        selected = read_engine(raw)
        error = None if selected != HERMES or ready else 'HERMES_NOT_READY'
    except EngineSelectionError:
        selected = None
        error = 'INVALID_ENGINE_SELECTION'
    return {
        'active_sales_engine': selected,
        'effective_sales_engine': selected if error is None else None,
        'target_default_engine': TARGET_DEFAULT,
        'hermes_live_ready': ready,
        'available_engines': [LANGGRAPH] + ([HERMES] if ready else []),
        'automatic_fallback': False,
        'error_code': error,
    }


def require_selectable(engine: str) -> None:
    if not isinstance(engine, str) or engine not in ENGINES:
        raise EngineSelectionError('Unknown sales engine.')
    if engine == HERMES and not live_hermes_ready():
        raise EngineUnavailable('Hermes live routing is not certified in HEI-01A.')
