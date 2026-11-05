"""Resolve the active offer without turning an old pending task into consent.

This module does not classify commercial intent: the published LLM contract
does that. It bounds deterministic selections and execution to current evidence.
"""
import re
from .conversation_scope import scoped_messages_query
from .models import SalesConversation, SalesMessage

ORDINALS = {"first": 0, "primero": 0, "primera": 0, "second": 1,
            "segundo": 1, "segunda": 1, "third": 2, "tercero": 2, "tercera": 2}
SCHEDULING_INTENTS = {"request_appointment", "select_appointment_slot"}


def choice_index(text):
    normalized = re.sub(r"[^\wáéíóúñ]+", " ", text.casefold()).strip()
    match = re.fullmatch(
        r"(?:(?:the|la|el) )?(?:(?:option|opción|opcion|number|número|numero) )?"
        r"(\d{1,4}|first|second|third|primero|primera|segundo|segunda|tercero|tercera)"
        r"(?: (?:option|opción|opcion|time|slot|horario))?", normalized,
    )
    if not match:
        return None
    value = match.group(1)
    return int(value) - 1 if value.isdigit() and int(value) > 0 else ORDINALS.get(value)


def latest_outbound(db, conversation_id):
    conversation = db.get(SalesConversation, conversation_id)
    if not conversation:
        return None
    return scoped_messages_query(db, conversation).filter(
        SalesMessage.direction == "outbound",
        SalesMessage.status.notin_(["failed", "cancelled"]),
    ).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).first()


def turn_context(db, conversation, lead=None):
    latest = latest_outbound(db, conversation.id)
    metadata = latest.metadata_json or {} if latest else {}
    kinds = [key for key in ("appointment_offer", "property_catalog_offer", "material_offer", "location_offer")
             if isinstance(metadata.get(key), dict)]
    # More than one selectable offer requires an explicit reference, not a guess.
    return {"latest_offer_message_id": latest.id if latest else None,
            "active_offer_kind": kinds[0] if len(kinds) == 1 else None,
            "ambiguous_offer": len(kinds) > 1,
            "offers": {key: metadata[key] for key in kinds},
            "pending_location": bool(lead and (lead.meta_form_data or {}).get("pending_location_request")),
            "pending_material_id": conversation.pending_asset_id}


def appointment_execution_allowed(result, routing=None):
    import math
    # A downstream executor must not revive an intention explicitly rejected
    # by the graph. Missing trace remains compatible with legacy callers.
    if (result.get("response_policy_trace") or {}).get("appointment_intent") is False:
        return False
    intents = {result.get("primary_intent") or result.get("intent"), *(result.get("secondary_intents") or [])}
    confidence = result.get("intent_confidence")
    threshold = float((routing or {}).get("minimum_confidence", .80))
    return bool(intents & SCHEDULING_INTENTS) and not (
        result.get("requires_clarification") or result.get("policy_violations")
        or intents & {"human_requested", "request_callback", "security_or_abuse", "opt_out"}
    ) and isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence) and threshold <= confidence <= 1


def location_continuation(db, conversation, lead, inbound):
    if not (lead.meta_form_data or {}).get("pending_location_request"):
        return False
    latest = latest_outbound(db, conversation.id)
    if not latest:
        return False
    metadata = latest.metadata_json or {}
    if "request_visit_location" not in {a.get("type") for a in metadata.get("proposed_actions", []) if isinstance(a, dict)}:
        return False
    # Exact numeric choices are safe only in the current location question.
    if choice_index(inbound) is not None:
        return True
    from app.modules.projects.locations import locations_for_project
    from app.modules.projects.models import Project
    project = db.get(Project, conversation.project_id)
    text = inbound.casefold().strip().rstrip(".!?")
    return any(text in {str(item.get("label", "")).casefold(), str(item.get("address", "")).casefold()}
               for item in locations_for_project(project) if text)
