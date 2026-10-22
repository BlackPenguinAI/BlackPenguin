from __future__ import annotations

import re
from typing import Any


APPOINTMENT_TERMS = re.compile(
    r"\b(appointment|visit|tour|showing|schedule|availability|available time|"
    r"cita|visita|recorrido|agendar|horario|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|"
    r"works for me)\b",
    re.IGNORECASE,
)
AFFIRMATIVE = re.compile(r"^\s*(yes|yeah|sure|okay|ok|please|sí|si|claro|de acuerdo)\b", re.IGNORECASE)
UNSOLICITED_APPOINTMENT_SENTENCE = re.compile(
    r"(?is)(?:^|(?<=[.!?])\s+)"
    r"(?:would you like|do you want|shall i|can i|i can|we can)"
    r"[^.!?]{0,140}\b(?:schedule|arrange|book|offer)\b"
    r"[^.!?]{0,100}\b(?:appointment|visit|tour|showing)\b[.!?]?"
)
GREETING_ONLY = re.compile(r"^\s*(hi|hello|hey|good (?:morning|afternoon|evening))[!.\s]*$", re.IGNORECASE)
INTRODUCTION_TERMS = re.compile(
    r"\b(i(?:'m| am) .*sales agent|thanks for your interest|how can i assist|how can i help)\b",
    re.IGNORECASE,
)
TOPIC_PATTERNS = {
    "property_types": re.compile(r"\b(unit types?|property types?|bedrooms?|homes?|models?)\b", re.IGNORECASE),
    "inventory": re.compile(r"\b(available units?|availability|inventory|how many)\b", re.IGNORECASE),
    "pricing": re.compile(r"\b(price|prices|pricing|cost|starting at|budget)\b", re.IGNORECASE),
    "financing": re.compile(r"\b(financing|finance|mortgage|loan|payment method)\b", re.IGNORECASE),
    "delivery": re.compile(r"\b(move[- ]?in|delivery|ready|completion)\b", re.IGNORECASE),
    "amenities": re.compile(r"\b(amenities|features|included)\b", re.IGNORECASE),
    "assets": re.compile(r"\b(brochure|floor plan|blueprint|price list|document|pdf|plans?)\b", re.IGNORECASE),
    "appointment": APPOINTMENT_TERMS,
    "callback": re.compile(r"\b(call me|callback|phone call|speak to (?:sales|a person|someone))\b", re.IGNORECASE),
}


def plain_channel_text(value: str | None) -> str | None:
    """Remove presentation Markdown that is rendered literally by SMS/WhatsApp."""
    if value is None:
        return None
    text = value.replace("```", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "• ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def normalized_reply(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def repeats_recent_assistant_reply(reply: str | None, history: list[dict[str, str]]) -> bool:
    candidate = normalized_reply(reply)
    if not candidate:
        return False
    recent = [
        normalized_reply(item.get("content"))
        for item in history[-8:]
        if item.get("role") == "assistant"
    ]
    return candidate in {item for item in recent if item}


def repeats_introduction_after_greeting(
    reply: str | None, inbound: str | None, history: list[dict[str, str]],
) -> bool:
    """Catch semantic welcome repetition after the proactive first contact."""
    if not GREETING_ONLY.match(inbound or "") or not INTRODUCTION_TERMS.search(reply or ""):
        return False
    return any(
        item.get("role") == "assistant" and INTRODUCTION_TERMS.search(item.get("content", ""))
        for item in history[:-1]
    )


def requested_topics(inbound: str | None) -> set[str]:
    return {name for name, pattern in TOPIC_PATTERNS.items() if pattern.search(inbound or "")}


def _topic_evidenced(topic: str, reply: str | None, actions: list[Any]) -> bool:
    text = (reply or "").casefold()
    if topic == "inventory":
        return bool(re.search(r"\b\d+\b[^.!?]{0,40}\b(?:available|homes?|units?)\b|\bavailable\b[^.!?]{0,40}\b\d+\b", text))
    if topic == "pricing":
        return bool(re.search(r"(?:\$|\b(?:usd|pen|mxn|ars)\b|\b(?:price|pricing|cost|starts? at)\b)", text))
    if topic == "financing":
        return bool(re.search(r"\b(financ|mortgage|loan|cash|bank|payment)\w*\b", text))
    if topic == "delivery":
        return bool(re.search(r"\b(move[- ]?in|delivery|ready|completion|immediate)\w*\b", text))
    if topic == "amenities":
        return bool(re.search(r"\b(amenit|feature|pool|gym|club|park|security)\w*\b", text))
    if topic == "assets":
        return "http" in text or "share_asset" in action_types(actions)
    if topic == "property_types":
        return bool(re.search(r"\b(?:\d+\s*(?:br|bed)|bedroom|unit type|home type|property type)\w*\b", text))
    return True


def complete_requested_commercial_topics(
    reply: str | None, *, inbound: str | None, actions: list[Any], commercial: dict[str, Any],
) -> tuple[str | None, list[str]]:
    """Append only missing, confirmed answers from the canonical context.

    This is intentionally deterministic: a multi-part lead question must not
    silently lose inventory or price facts merely because the model focused on
    one clause.
    """
    requested = requested_topics(inbound)
    missing = {topic for topic in requested if not _topic_evidenced(topic, reply, actions)}
    additions: list[str] = []
    property_types = commercial.get("property_types") or []
    inventory = commercial.get("inventory") or []
    facts = commercial.get("confirmed_project_facts") or {}
    if "property_types" in missing and property_types:
        additions.append("Home types: " + ", ".join(str(item.get("property_type")) for item in property_types if item.get("property_type")) + ".")
    if "inventory" in missing and inventory:
        if commercial.get("inventory_source") == "individual_units":
            count = sum(str(item.get("status") or "").casefold() in {"available", "active", "ready"} for item in inventory)
        else:
            values = [item.get("available_units") for item in inventory if item.get("available_units") is not None]
            count = sum(int(value) for value in values) if values else None
        if count is not None:
            additions.append(f"Current availability: {count} home{'s' if count != 1 else ''}.")
    if "pricing" in missing:
        candidates = [
            (item.get("starting_price") if item.get("starting_price") is not None else item.get("price"), item.get("currency"))
            for item in inventory
            if item.get("starting_price") is not None or item.get("price") is not None
        ]
        if candidates:
            amount, currency = min(candidates, key=lambda item: float(item[0]))
            additions.append(f"Confirmed starting price: {currency or ''} {float(amount):,.0f}.".replace(":  ", ": "))
    if "financing" in missing:
        value = facts.get("payment_methods") or facts.get("financing_options") or facts.get("financing")
        if value:
            additions.append(f"Payment and financing: {value}.")
    if "delivery" in missing:
        value = facts.get("delivery_dates") or facts.get("delivery_timeline")
        if value:
            additions.append(f"Delivery: {value}.")
    if "amenities" in missing:
        value = facts.get("amenities")
        if value:
            rendered = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            additions.append(f"Amenities: {rendered}.")
    if not additions:
        return reply, []
    base = (reply or "").strip()
    completed = f"{base}\n\n" if base else ""
    completed += "\n".join(f"• {item}" for item in additions)
    return completed, sorted(missing)


def appointment_intent_present(inbound: str, history: list[dict[str, str]]) -> bool:
    if APPOINTMENT_TERMS.search(inbound or ""):
        return True
    if not AFFIRMATIVE.search(inbound or ""):
        return False
    previous = next(
        (item.get("content", "") for item in reversed(history[:-1]) if item.get("role") == "assistant"),
        "",
    )
    return bool(APPOINTMENT_TERMS.search(previous))


def remove_unsolicited_appointment_offer(reply: str | None) -> str | None:
    if reply is None:
        return None
    cleaned = UNSOLICITED_APPOINTMENT_SENTENCE.sub("", reply)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def action_types(actions: list[Any]) -> set[str]:
    return {
        str(action.get("type"))
        for action in actions
        if isinstance(action, dict) and action.get("type")
    }

