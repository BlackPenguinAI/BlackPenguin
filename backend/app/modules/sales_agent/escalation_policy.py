"""Trusted escalation disposition, shared by inbound, simulation and follow-ups.

Model review proposals are not permission to pause a conversation. Published
staff routing policy controls ordinary gaps; protected violations remain hard.
"""
import re
from .response_policy import topics_for_turn
from app.modules.governance.services import escalation_reason, enqueue_notification


def apply_escalation_policy(result, *, inbound, routing=None, event_kind="lead_message"):
    result = dict(result)
    routing = routing or {}
    intents = {result.get("primary_intent") or result.get("intent"), *(result.get("secondary_intents") or [])}
    actions = [a for a in result.get("proposed_actions", []) if isinstance(a, dict)]
    commercial = result.get("commercial_context") or {}
    violations = list(result.get("policy_violations") or [])
    # Invalid model IDs never authorize disclosure. Discard them even when no
    # alternative file exists; absence of a file is not a security incident.
    repairable = {"share_asset_missing_id", "share_asset_not_approved"}
    ids = {a.get("asset_id") for a in commercial.get("available_assets", [])}
    actions = [a for a in actions if a.get("type") != "share_asset" or a.get("asset_id") in ids]
    violations = [v for v in violations if v not in repairable]
    requested_review = bool(result.get("requires_human")) or any(a.get("type") in {"request_human_review", "request_callback"} for a in actions)
    prior = result.get("escalation_decision") or {}
    # Re-evaluation at the dispatch boundary must retain a graph's advisory
    # decision after the model's review action was consumed there.
    requested_review = requested_review or prior.get("disposition") == "notify_sales"
    confidence = result.get("intent_confidence")
    trusted = isinstance(confidence, (float, int)) and not isinstance(confidence, bool) and float(routing.get("minimum_confidence", .8)) <= confidence <= 1
    reason = escalation_reason(inbound) if event_kind == "lead_message" else None
    disposition = "pause" if reason else "continue"
    if event_kind == "lead_message" and (inbound.strip().upper() in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"} or trusted and "opt_out" in intents):
        disposition, reason = "opt_out", "LEAD_OPTED_OUT"
    elif violations:
        disposition, reason = "pause", "POLICY_VIOLATION"
    elif event_kind == "lead_message" and trusted and "security_or_abuse" in intents:
        disposition, reason = "pause", "SECURITY"
    elif event_kind == "lead_message" and trusted and "human_requested" in intents:
        disposition, reason = "pause", "HUMAN_REQUESTED"
    elif not reason:
        missing_material = "assets" in topics_for_turn(inbound, intents) and not commercial.get("available_assets")
        low_confidence = bool(result.get("requires_clarification")) or not trusted
        gap = "MISSING_MATERIAL" if missing_material else "LOW_CONFIDENCE" if low_confidence else "MISSING_INFORMATION"
        flag = {"MISSING_MATERIAL": "pause_on_missing_material", "LOW_CONFIDENCE": "pause_on_low_confidence", "MISSING_INFORMATION": "pause_on_missing_information"}[gap]
        if (missing_material or low_confidence or requested_review) and routing.get(flag) is True:
            disposition, reason = "pause", gap
        elif requested_review:
            disposition, reason = "notify_sales", gap
    actions = [a for a in actions if a.get("type") not in {"request_human_review", "request_callback"}]
    if disposition == "pause":
        actions = [{"type": "request_callback" if reason == "HUMAN_REQUESTED" else "request_human_review"}]
    if disposition == "opt_out":
        actions = []
    decision = {"version": "sales-escalation-v1", "disposition": disposition, "reason": reason,
                "conversation_paused": disposition in {"pause", "opt_out"},
                "applied_pause_policy": {key: routing.get(key) is True for key in ("pause_on_missing_information", "pause_on_missing_material", "pause_on_low_confidence")}}
    result.update(proposed_actions=actions, policy_violations=violations,
                  requires_human=disposition == "pause", escalation_decision=decision)
    if disposition == "notify_sales":
        reply = result.get("proposed_reply") or ""
        def keep_safe_sentence(match):
            return "" if re.search(r"\b(?:human review|hold on|(?:chat|conversation|AI) (?:is |has been )?paused|transferr?ing you|cannot continue)\b", match.group(), re.I) else match.group()
        cleaned = re.sub(r"[^.!?\n]+(?:[.!?]|$)", keep_safe_sentence, reply).strip()
        result["proposed_reply"] = cleaned or "Some information needs verification, but I can continue helping with the approved Project information."
    result["response_policy_trace"] = {**result.get("response_policy_trace", {}), "escalation": decision, "requires_human": result["requires_human"]}
    return result


def notify_sales(db, *, conversation, lead, decision, event_id, evidence):
    """Auditable, idempotent notice, without a case, pause or stage mutation."""
    return enqueue_notification(db, company_id=conversation.company_id, project_id=conversation.project_id,
        event_type="sales_review_requested", entity_type="lead", entity_id=lead.id,
        payload={"title": "Sales review requested — AI conversation remains active",
                 "body": f"{lead.full_name}: {decision['reason'].replace('_', ' ').title()}. The AI conversation remains active.",
                 "reason": decision["reason"], "conversation_id": conversation.id,
                 "evidence": evidence[:500], "recipient_roles": ["admin", "sales"],
                 "action_url": f"/app/agent?conversation={conversation.id}"},
        dedupe_key=f"sales-review:{conversation.id}:{event_id}")


def escalation_reply(decision):
    reason = decision.get("reason")
    if decision.get("disposition") == "opt_out":
        return "You have been unsubscribed and will not receive further messages."
    if reason == "SECURITY":
        return "I can't assist with unauthorized access or unsafe requests. This conversation has been paused for human security review."
    if reason == "HUMAN_REQUESTED":
        return "I've sent your request and this conversation context to the Sales team. The AI conversation is paused so a person can follow up."
    label = {"POLICY_VIOLATION": "a protected policy blocked the automated response", "MISSING_MATERIAL": "the requested approved material is missing", "MISSING_INFORMATION": "the required verified information is missing", "LOW_CONFIDENCE": "the request needs clarification", "LEGAL_QUESTION": "legal review is required", "COMPLEX_NEGOTIATION": "the requested commercial exception needs approval"}.get(reason, "human review is required")
    return f"The AI conversation has been paused because {label}. I've sent the request and conversation context for human review."
