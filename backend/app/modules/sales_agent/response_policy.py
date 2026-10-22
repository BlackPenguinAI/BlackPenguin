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

