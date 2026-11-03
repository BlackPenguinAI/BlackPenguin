"""Shared meaning of persisted onboarding decisions (never permissions)."""

APPROVED_STATUSES = frozenset({"confirmed", "corrected_by_user"})


def field_approved(state: dict | None) -> bool:
    state = state or {}
    return state.get("status") in APPROVED_STATUSES and state.get("applicable", True) is not False


def field_resolved(state: dict | None, *, allow_deferred: bool = False) -> bool:
    state = state or {}
    if field_approved(state):
        return True
    if state.get("status") == "not_applicable" and state.get("applicable") is False:
        return True
    return allow_deferred and state.get("status") == "deferred"
