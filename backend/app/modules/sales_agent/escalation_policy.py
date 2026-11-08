"""Trusted escalation disposition, shared by inbound, simulation and follow-ups.

Model review proposals are not permission to pause a conversation. Ordinary
gaps remain advisory even with old pause flags; verified control stays hard.
"""
import re
from .response_policy import topics_for_turn
from app.modules.governance.services import escalation_reason, enqueue_notification, request_attribution
from .continuity_policy import explicit_opt_out, evidenced_pause_reason, HARD_VIOLATIONS


def apply_escalation_policy(result, *, inbound, routing=None, event_kind="lead_message", dismissed_reason=None):
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
    uncertain_opt_out = event_kind == "lead_message" and "opt_out" in intents and not explicit_opt_out(inbound)
    attribution = request_attribution(inbound)
    reason = evidenced_pause_reason(inbound) if event_kind == "lead_message" else None
    if reason == dismissed_reason:
        reason = None
    reason_source = "deterministic_current_request" if reason else None
    protected = (result.get("intent_entities") or {}).get("protected_request")
    advisory_reason = escalation_reason(inbound) if event_kind == 'lead_message' else None
    protected_accepted = advisory_reason in {'LEGAL_QUESTION','COMPLEX_NEGOTIATION'}
    if event_kind == "lead_message" and not reason and trusted and not result.get("requires_clarification") and isinstance(protected, dict):
        kind, evidence = protected.get("kind"), protected.get("evidence")
        if isinstance(kind, str) and kind in {"legal_review", "commercial_exception"} and isinstance(evidence, str) and 0 < len(evidence.strip()) <= 500 and evidence.casefold() in attribution["current_text"].casefold():
            # A model's commercial/legal label is advisory, never authority
            # to stop the conversation. Hold actions and notify staff below.
            protected_accepted = True
            advisory_reason = {'legal_review':'LEGAL_QUESTION','commercial_exception':'COMPLEX_NEGOTIATION'}[kind]
    disposition = "pause" if reason else "continue"
    applicable_conditions = []
    matched_pause_rules = []
    if event_kind == "lead_message" and explicit_opt_out(inbound):
        disposition, reason = "opt_out", "LEAD_OPTED_OUT"
        reason_source = "literal_opt_out" if inbound.strip().upper() in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"} else "explicit_current_opt_out"
    elif HARD_VIOLATIONS.intersection(violations):
        disposition, reason = "pause", "POLICY_VIOLATION"
        reason_source = "protected_policy_validation"
    elif not reason:
        missing_material = "assets" in topics_for_turn(inbound, intents) and not commercial.get("available_assets")
        low_confidence = bool(result.get("requires_clarification")) or not trusted
        # Confidence is independent of collateral availability. Check every
        # applicable rule, then use this explicit precedence for the reason.
        rules = [("LOW_CONFIDENCE", "pause_on_low_confidence", low_confidence),
                 ("MISSING_MATERIAL", "pause_on_missing_material", missing_material),
                 ("MISSING_INFORMATION", "pause_on_missing_information", requested_review and not missing_material and not low_confidence)]
        applicable_conditions = [label for label, _, applies in rules if applies]
        # Legacy stored pause flags remain readable, but cannot turn an
        # ordinary gap or a bad interpretation into conversation control.
        matched_pause_rules = []
        if requested_review or applicable_conditions or violations or protected_accepted:
            disposition, reason = "notify_sales", advisory_reason if protected_accepted else next(iter(applicable_conditions), "MISSING_INFORMATION")
            reason_source = "sales_notice"
    unverified_control = event_kind == 'lead_message' and not reason_source == 'deterministic_current_request' and bool(intents & {'human_requested','security_or_abuse'}) and disposition != 'pause'
    if unverified_control:
        result['requires_clarification'] = True
        result['proposed_reply'] = ('Would you like me to transfer this conversation to the Sales team?' if 'human_requested' in intents
                                    else 'Could you clarify your request? I can help with approved property information or connect you with the Sales team.')
        actions = []
    # A rejected action is not permission to execute any other write from an
    # invalid turn. Keep a reply/clarification available without pausing.
    if (violations and disposition != 'pause') or protected_accepted:
        actions = []
        result['requires_clarification'] = True
        if protected_accepted and disposition != 'pause':
            result['proposed_reply'] = 'The Sales team needs to review that legal or commercial exception. I can continue helping with approved property information.'
    actions = [a for a in actions if a.get("type") not in {"request_human_review", "request_callback"}]
    if disposition == "pause":
        actions = [{"type": "request_callback" if reason == "HUMAN_REQUESTED" else "request_human_review"}]
    if disposition == "opt_out":
        actions = []
    elif uncertain_opt_out:
        result["requires_clarification"] = True
        # No commercial action is consent to continue contact. Ask only about
        # scope; do not book, share files or promise an unsubscribe here.
        actions = actions if disposition == "pause" else [{"type": "ask_qualification_question"}]
    decision = {"version": "sales-escalation-v2", "disposition": disposition, "reason": reason,
                "conversation_paused": disposition in {"pause", "opt_out"},
                "consent_clarification_required": uncertain_opt_out and disposition != "opt_out",
                "applicable_conditions": applicable_conditions, "matched_pause_rules": matched_pause_rules,
                "request_attribution": attribution, "reason_source": reason_source,
                "protected_request_accepted": protected_accepted,
                "unverified_control_request": unverified_control,
                "control_confirmation": 'human' if unverified_control and 'human_requested' in intents else None,
                "ignored_ordinary_pause_flags": [key for key in ('pause_on_missing_information','pause_on_missing_material','pause_on_low_confidence') if routing.get(key) is True],
                "applied_pause_policy": {key: routing.get(key) is True for key in ("pause_on_missing_information", "pause_on_missing_material", "pause_on_low_confidence")}}
    result.update(proposed_actions=actions, policy_violations=violations,
                  requires_human=disposition == "pause", escalation_decision=decision)
    if disposition == "notify_sales":
        reply = result.get("proposed_reply") or ""
        def keep_safe_sentence(match):
            return "" if re.search(r"\b(?:human review|hold on|(?:chat|conversation|AI) (?:is |has been )?paused|transferr?ing you|cannot continue)\b", match.group(), re.I) else match.group()
        cleaned = re.sub(r"[^.!?\n]+(?:[.!?]|$)", keep_safe_sentence, reply).strip()
        result["proposed_reply"] = cleaned or "Some information needs verification, but I can continue helping with the approved Project information."
    if uncertain_opt_out and disposition not in {"pause", "opt_out"}:
        result["proposed_reply"] = "Do you want to stop all messages from us, or only these offers? Reply STOP to unsubscribe from all messages."
    elif disposition != "opt_out" and re.search(r"\b(?:you (?:have been|are|were) (?:successfully )?(?:unsubscribed|opted out)|I(?:['’]ve| have) unsubscribed you|you will (?:not|no longer) receive (?:any |further |more )?messages)\b", result.get("proposed_reply") or "", re.I):
        # Confirmation belongs to the persisted opt-out operation, not to a
        # model sentence (including hallucinated scheduled follow-ups).
        result["proposed_reply"] = (escalation_reply(decision) if disposition == "pause" else
            "You can reply STOP to unsubscribe from all messages. How would you like to proceed?")
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


def cancel_followups_for_consent_clarification(db, *, conversation, lead):
    """Do not proactively chase a lead while asking what contact to stop."""
    from .models import SalesFollowUpJob
    lead.next_action_at = None
    db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == conversation.id,
        SalesFollowUpJob.status.in_(["pending", "processing"]),
    ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)


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
