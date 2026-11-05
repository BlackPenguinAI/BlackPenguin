"""Resolve objections against approved facts, never against a model apology."""
import re
from .response_policy import grounded_catalog_reply, complete_requested_commercial_topics, topics_for_turn, normalized_reply
from .monetary_policy import validate_monetary_reply

CORRECTION = re.compile(r"\b(?:that(?:['’]s| is) (?:wrong|incorrect|not right|not correct)|you (?:said|repeated|ignored|missed)|i (?:meant|asked)|not what i asked|correct (?:that|the)|you(?:'re| are) repeating|eso (?:es incorrecto|est[aá] mal)|dijiste|quise decir|me refiero|no es lo que|te ped[ií]|est[aá]s repitiendo)\b", re.I)
APOLOGY = re.compile(r"\b(?:i apologiz[es]?|sorry for (?:the|my)|disculpa|perd[oó]n)\b", re.I)


def correction_context(inbound, history, entities=None, proposed_reply=None):
    entities = entities or {}
    previous = next((m.get("content", "") for m in reversed(history) if m.get("role") == "assistant"), "")
    without_apology = re.sub(r"^\s*(?:I apologiz[es]?|I'm sorry|Sorry|Disculpa|Perd[oó]n)[^.!?\n]*[.!?]\s*", "", proposed_reply or "", flags=re.I)
    repeated_apology = bool(APOLOGY.search(proposed_reply or "") and previous and normalized_reply(without_apology) == normalized_reply(previous))
    active = bool(CORRECTION.search(inbound) or entities.get("correction_requested") is True or repeated_apology)
    return {"requested": active, "challenged_message": previous if active else None,
            "lead_correction": inbound if active else None,
            "challenged_topic": entities.get("challenged_topic")}


def resolve_correction(*, inbound, history, commercial, intents, entities, proposed_reply, clarify_only=False):
    trace = correction_context(inbound, history, entities, proposed_reply)
    if not trace["requested"]:
        return proposed_reply, trace
    topics = topics_for_turn(inbound, intents) - {"appointment", "callback"}
    topic = entities.get("challenged_topic")
    if topic in {"pricing", "inventory", "property_types", "financing", "delivery", "amenities", "location", "assets"}:
        topics.add(topic)
    selected = next((p for p in commercial.get("property_types", []) if p.get("id") == commercial.get("selected_property_type_id")), None)
    trace.update(selected_property_type_id=commercial.get("selected_property_type_id"),
                 approved_revision=commercial.get("approved_revision"),
                 fact_provenance=commercial.get("fact_provenance", {}), topics=sorted(topics))
    if not topics or clarify_only:
        name = f" about {selected['property_type']}" if selected else " in my previous answer"
        trace["resolution"] = "clarify_disputed_detail"
        return f"Which detail{name} should I recheck: the layout, price, availability, or another specific point? I haven't confirmed a correction yet.", trace
    mapped = {"pricing": "request_pricing", "inventory": "request_inventory", "property_types": "request_property_details",
              "financing": "request_financing", "delivery": "request_delivery", "amenities": "request_amenities", "location": "request_location"}
    checked_intents = [mapped[t] for t in topics if t in mapped]
    body = grounded_catalog_reply(inbound, commercial, intents=checked_intents) if topics & {"pricing", "inventory", "property_types"} else ""
    body, _ = complete_requested_commercial_topics(body or "", inbound=inbound, actions=[], commercial=commercial, intents=checked_intents)
    if not body:
        body = "I'll check the approved materials for the information you requested; I haven't confirmed a correction to the earlier answer."
    trace["resolution"] = "rechecked_approved_evidence"
    # Do not assert a source changed simply because the lead disagreed. Actual
    # approved values follow; the earlier/model text remains in diagnostics.
    _, previous_price_check = validate_monetary_reply(trace["challenged_message"], commercial)
    trace["previous_monetary_validation"] = previous_price_check
    prefix = ("The amount in my earlier answer was not supported by the current approved information. Please use the verified values below."
        if "pricing" in topics and previous_price_check["replaced"] else
        "Thanks for flagging that. I rechecked the current approved information below; this does not confirm a change to the Project data. Which specific detail differs from what you expected?")
    return f"{prefix}\n\n{body}", trace
