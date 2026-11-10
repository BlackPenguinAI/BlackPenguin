from __future__ import annotations

import re
from typing import Any
from app.modules.money import format_amount


VISUAL_MATERIAL_TERMS = re.compile(
    r"\b(?:pictures?|photos?|images?|gallery|renderings?|brochures?|pdfs?|documents?|"
    r"floor\s*plans?|blueprints?|virtual\s*tours?|360(?:°|\s*degrees?)?|"
    r"fotos?|im[aá]genes?|galer[ií]a|renders?|folletos?|documentos?|planos?|recorridos?\s+virtuales?)\b",
    re.IGNORECASE,
)
APPOINTMENT_TERMS = re.compile(
    r"\b(appointment|showing|schedule|book|available time|time slot|"
    r"in[- ]person (?:visit|tour|showing)|visit (?:the|this|a) (?:property|project|unit|home)|"
    r"cita|visita presencial|agendar|programar una visita|reservar una cita|"
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
    "property_types": re.compile(
        r"\b(?:unit|property|home)\s+types?\b|\btypes?\s+of\s+(?:units?|properties|homes?)\b|"
        r"\b(?:bedrooms?|homes?|models?|layouts?|typologies?)\b",
        re.IGNORECASE,
    ),
    "inventory": re.compile(
        r"\bavailable\s+(?:units?|homes?|properties)\b|"
        r"\b(?:units?|homes?|properties)\s+(?:you\s+have\s+)?available\b|"
        r"\bavailability\b|\binventory\b|\bhow many\b",
        re.IGNORECASE,
    ),
    "pricing": re.compile(r"\b(price|prices|pricing|cost|starting at|budget)\b", re.IGNORECASE),
    "financing": re.compile(r"\b(financing|finance|mortgage|loan|payment method)\b", re.IGNORECASE),
    "delivery": re.compile(r"\b(move[- ]?in|delivery|ready|completion)\b", re.IGNORECASE),
    "amenities": re.compile(r"\b(amenities|features|included)\b", re.IGNORECASE),
    "assets": re.compile(
        r"\b(?:brochures?|floor\s*plans?|blueprints?|price\s*lists?|documents?|pdfs?|plans?|"
        r"sales\s+materials?|virtual\s+tours?|walkthroughs?|360(?:°|\s*degrees?)?|"
        r"pictures?|photos?|images?|gallery|renderings?|fotos?|im[aá]genes?|galer[ií]a|renders?)\b",
        re.IGNORECASE,
    ),
    "appointment": APPOINTMENT_TERMS,
    "callback": re.compile(r"\b(call me|callback|phone call|speak to (?:sales|a person|someone))\b", re.IGNORECASE),
}


def _strip_emphasis_outside_urls(text, pattern, replacement):
    spans = [(match.start(), match.end()) for match in re.finditer(r"https?://[^\s]+", text)]
    def replace(match):
        if any(start <= match.start() < end or start < match.end() < end for start, end in spans):
            return match.group(0)
        return replacement(match)
    return re.sub(pattern, replace, text)


def plain_channel_text(value: str | None) -> str | None:
    """Remove presentation Markdown that is rendered literally by SMS/WhatsApp."""
    if value is None:
        return None
    text = value.replace("```", "")
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda match: match.group(2) if match.group(1).strip().rstrip("/") in match.group(2) else f"{match.group(1).strip()}: {match.group(2)}",
        text,
    )
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = _strip_emphasis_outside_urls(text, r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2))
    text = _strip_emphasis_outside_urls(text, r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: m.group(1))
    text = re.sub(r"(?m)^[ \t]*[-*][ \t]+", "• ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def concise_channel_text(value: str | None, channel: str) -> str | None:
    """Keep mobile replies readable without cutting a sentence or secure URL."""
    text = plain_channel_text(value)
    if not text:
        return text
    limit = 700 if channel == "sms" else 1200
    if len(text) <= limit:
        return text
    # Keep paragraph and list boundaries. Flattening them here made separate
    # property records render as one malformed WhatsApp/SMS paragraph.
    segments = [segment for segment in re.split(r"(\n+|(?<=[.!?])[ \t]+)", text) if segment]
    kept: list[str] = []
    length = 0
    for segment in segments:
        if segment.isspace():
            if not kept:
                continue
            separator = "\n\n" if "\n\n" in segment else ("\n" if "\n" in segment else " ")
            if length + len(separator) > limit - 55:
                break
            kept.append(separator)
            length += len(separator)
            continue
        content = segment.strip()
        if not content:
            continue
        if length + len(content) > limit - 55:
            break
        kept.append(content)
        length += len(content)
    base = "".join(kept).strip() or text[:limit - 55].rsplit(" ", 1)[0]
    return f"{base}\n\nI can share more detail on any of these points."


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


INTENT_TOPICS = {
    "request_property_catalog": "property_types", "request_property_details": "property_types",
    "request_inventory": "inventory", "request_pricing": "pricing", "request_financing": "financing",
    "request_delivery": "delivery", "request_amenities": "amenities", "request_location": "location",
    "request_visual_material": "assets", "request_document": "assets", "request_virtual_tour": "assets",
    "request_appointment": "appointment", "select_appointment_slot": "appointment",
}


def topics_for_turn(inbound, intents=()):
    return requested_topics(inbound) | {INTENT_TOPICS[i] for i in intents if i in INTENT_TOPICS}


def render_channel_text(value, channel="sms"):
    """One lossless final format for model, catalog and executor replies."""
    text = plain_channel_text(value)
    if not text:
        return text
    # Repair inline numbering, without changing decimal prices or URLs.
    original=text
    def separate_number(match):
        prefix=original[:match.start()]
        if re.search(r'(?:quantity|count|units available):$',prefix,re.I):return match.group(0)
        return '\n\n'
    text = re.sub(r"(?<=\S)[ \t]+(?=\d{1,4}[.)][ \t]+)", separate_number, text)
    text = re.sub(r"(?<=\S)[ \t]+(?=•[ \t]+)", "\n", text)
    text = re.sub(r"(?<!\n)\n(?=\d{1,4}[.)][ \t]+)", "\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_channel_text(value, channel="sms"):
    """Split by paragraphs/lines, never truncate options or split a secure URL."""
    text = render_channel_text(value, channel) or ""
    limit = 1400 if channel == "sms" else 3500
    if len(text) <= limit:
        return [text] if text else []
    chunks = []
    remaining = text
    while len(remaining) > limit:
        boundary = remaining.rfind("\n\n", 0, limit + 1)
        if boundary <= 0:
            boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary <= 0:
            boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary <= 0:
            # A single opaque token must stay intact, even if the provider
            # ultimately rejects it. Never issue a corrupted download URL.
            boundary = next((i for i, c in enumerate(remaining) if c.isspace()), len(remaining))
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


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
        return "confirmed details for" in text or bool(re.search(r"\b(?:\d+\s*(?:br|bed)|bedroom|unit type|home type|property type)\w*\b", text))
    if topic == "location":
        return bool(re.search(r"\b(?:address|location|located)\b", text))
    return True


def _render_fact_value(value: Any) -> str:
    """Render approved structured values without leaking Python/JSON syntax."""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(
            rendered for item in value
            if (rendered := _render_fact_value(item))
        )
    if isinstance(value, dict):
        return ", ".join(
            f"{str(key).replace('_', ' ')}: {_render_fact_value(item)}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).strip() if value is not None else ""


def complete_requested_commercial_topics(
    reply: str | None, *, inbound: str | None, actions: list[Any], commercial: dict[str, Any],
    intents=(),
) -> tuple[str | None, list[str]]:
    """Append only missing, confirmed answers from the canonical context.

    This is intentionally deterministic: a multi-part lead question must not
    silently lose inventory or price facts merely because the model focused on
    one clause.
    """
    requested = topics_for_turn(inbound, intents)
    missing = {topic for topic in requested if not _topic_evidenced(topic, reply, actions)}
    additions: list[str] = []
    property_types = commercial.get("property_types") or []
    inventory = commercial.get("inventory") or []
    selected = next((item for item in property_types if item.get("id") == commercial.get("selected_property_type_id")), None)
    if selected:
        property_types = [selected]
        inventory = [item for item in inventory if item.get("id") == selected.get("id") or item.get("property_type") == selected.get("property_type")]
    facts = commercial.get("confirmed_project_facts") or {}
    if "property_types" in missing and property_types:
        additions.append("Home types: " + ", ".join(str(item.get("property_type")) for item in property_types if item.get("property_type")) + ".")
    if "inventory" in missing and inventory:
        if commercial.get("inventory_source") == "individual_units":
            trusted = [item for item in inventory if item.get("inventory_updated_at")]
            count = (
                sum(str(item.get("status") or "").casefold() in {"available", "active", "ready"} for item in trusted)
                if trusted else None
            )
        else:
            values = [
                item.get("available_units") for item in inventory
                if item.get("available_units") is not None and item.get("inventory_updated_at")
            ]
            count = sum(int(value) for value in values) if values else None
        if count is not None:
            incomplete = len(trusted) < len(inventory) if commercial.get("inventory_source") == "individual_units" else len(values) < len(inventory)
            additions.append(f"{'Verified subtotal' if incomplete else 'Current availability'}: {count} home{'s' if count != 1 else ''}." + (" Availability for the remaining records is not confirmed." if incomplete else ""))
    if "pricing" in missing:
        candidates = [
            (item.get("starting_price") if item.get("starting_price") is not None else item.get("price"), item.get("currency"))
            for item in inventory
            if item.get("starting_price") is not None or item.get("price") is not None
        ]
        for currency in sorted({currency for _, currency in candidates if currency}):
            amount = min(amount for amount, code in candidates if code == currency)
            additions.append(f"Confirmed starting price: {currency} {format_amount(amount)}.")
    if "financing" in missing:
        value = facts.get("payment_methods") or facts.get("financing_options") or facts.get("financing")
        if value:
            additions.append(f"Payment and financing: {_render_fact_value(value)}.")
    if "delivery" in missing:
        value = facts.get("delivery_dates") or facts.get("delivery_timeline")
        if value:
            additions.append(f"Delivery: {_render_fact_value(value)}.")
    if "amenities" in missing:
        value = facts.get("amenities")
        if value:
            rendered = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            additions.append(f"Amenities: {rendered}.")
    if "location" in missing:
        value = facts.get("exact_address") or facts.get("address")
        if value:
            additions.append(f"Location: {_render_fact_value(value)}.")
        else:
            additions.append("The Project location has not been confirmed in the available information.")
    if "inventory" in missing and not any("availability" in item.casefold() or "subtotal" in item.casefold() for item in additions):
        additions.append("Current unit availability has not been confirmed.")
    if "pricing" in missing and not any("price" in item.casefold() for item in additions):
        additions.append("Current pricing has not been confirmed.")
    for topic, label in (("financing", "Financing terms"), ("delivery", "Delivery timing"), ("amenities", "Amenities")):
        if topic in missing and not any(label.casefold().split()[0] in item.casefold() for item in additions):
            if not (topic == "delivery" and "being verified" in (reply or "")):
                additions.append(f"{label} have not been confirmed in the approved information available here.")
    if not additions:
        return reply, []
    base = (reply or "").strip()
    completed = f"{base}\n\n" if base else ""
    completed += "\n".join(f"• {item}" for item in additions)
    return completed, sorted(missing)


def grounded_catalog_reply(inbound: str | None, commercial: dict[str, Any], *, intents=()) -> str | None:
    """Render catalog facts predictably for mobile channels.

    The model may choose what to discuss, but it must not concatenate numbered
    records or turn absent price and inventory fields into invented values.
    """
    items = commercial.get("property_types") or []
    text = (inbound or "").casefold()
    selected_index: int | None = None
    selected_id = commercial.get("selected_property_type_id")
    if selected_id:
        selected_index = next((i for i, item in enumerate(items) if item.get("id") == selected_id), None)
    numbered = re.search(r"\b(?:option|number|unit|type)\s*(\d{1,2})\b", text)
    if selected_index is None and numbered and 1 <= int(numbered.group(1)) <= len(items) and not commercial.get("selection_context_required"):
        selected_index = int(numbered.group(1)) - 1
    elif selected_index is None:
        for index, item in enumerate(items):
            name = str(item.get("property_type") or "").strip().casefold()
            if name and len(name) >= 4 and name in text:
                selected_index = index
                break
    topics = topics_for_turn(inbound, intents)
    if selected_index is None and not topics.intersection({"property_types", "inventory", "pricing"}):
        return None
    if not items:
        return "The detailed property catalog has not been confirmed yet. That does not mean other options are unavailable; I can help with the approved Project information."

    if selected_index is not None:
        item = items[selected_index]
        name = str(item.get("property_type") or f"Home type {selected_index + 1}").strip()
        lines = [f"Here are the confirmed details for {name}:"]
        detail_values = (
            ("Bedrooms", item.get("bedrooms")),
            ("Bathrooms", item.get("bathrooms")),
        )
        for label, value in detail_values:
            if value is not None:
                lines.append(f"• {label}: {value:g}")
        area_min, area_max, area_unit = item.get("area_min"), item.get("area_max"), item.get("area_unit")
        if area_min is not None or area_max is not None:
            area = f"{area_min:g}" if area_min is not None else ""
            if area_max is not None and area_max != area_min:
                area = f"{area}–{area_max:g}" if area else f"Up to {area_max:g}"
            lines.append(f"• Area: {area} {area_unit or ''}".rstrip())
        if item.get("starting_price") is not None and item.get("currency"):
            lines.append(f"• Starting price: {format_amount(item['starting_price'])} {item['currency']}")
        if item.get("available_units") is not None and item.get("inventory_updated_at"):
            lines.append(f"• Confirmed availability: {item['available_units']} unit{'s' if item['available_units'] != 1 else ''}")
        elif "inventory" in topics:
            lines.append("• Current availability for this option has not been confirmed.")
        description = str(item.get("description") or "").strip()
        if description:
            lines.extend(["", description])
        lines.extend(["", "What would you like to review next about this option?"])
        return "\n".join(lines)

    # Every confirmed option must be visible. The summaries remain compact and
    # the detailed view is reserved for the option selected by the lead.
    visible = items
    project_name = str((commercial.get("confirmed_project_facts") or {}).get("project_name") or "").strip()
    lines = [
        f"{project_name} currently offers these confirmed home types:"
        if project_name else "Here are the confirmed home types:"
    ]
    has_price = False
    has_inventory = False
    for index, item in enumerate(visible, 1):
        name = str(item.get("property_type") or f"Home type {index}").strip()
        lines.extend(["", f"{index}. {name}"])
        details: list[str] = []
        if item.get("bedrooms") is not None:
            details.append(f"{item['bedrooms']:g} bedroom{'s' if float(item['bedrooms']) != 1 else ''}")
        area_min, area_max, area_unit = item.get("area_min"), item.get("area_max"), item.get("area_unit")
        if area_min is not None or area_max is not None:
            area = f"{area_min:g}" if area_min is not None else ""
            if area_max is not None and area_max != area_min:
                area = f"{area}–{area_max:g}" if area else f"Up to {area_max:g}"
            details.append(f"{area} {area_unit or ''}".rstrip())
        if item.get("starting_price") is not None and item.get("currency"):
            has_price = True
            details.append(f"from {format_amount(item['starting_price'])} {item['currency']}")
        if item.get("available_units") is not None and item.get("inventory_updated_at"):
            has_inventory = True
            if "inventory" in topics:
                details.append(f"{item['available_units']} currently available")
        description = str(item.get("description") or "").strip()
        if details:
            lines.append("   " + " · ".join(details) + ".")
        elif description:
            summary = description.split(".", 1)[0].strip()
            lines.append(f"   {summary[:160]}.")

    if "pricing" in topics and not has_price:
        lines.extend(["", "Current pricing has not been confirmed."])
    if "inventory" in topics and not has_inventory:
        lines.extend(["", "Current unit availability has not been confirmed."])
    elif "inventory" in topics and any(item.get("available_units") is None or not item.get("inventory_updated_at") for item in items):
        lines.extend(["", "Availability for the remaining types has not been confirmed."])
    if commercial.get("catalog_coverage", {}).get("exhaustive") is False:
        lines.extend(["", "These are the options I have confirmed; other options have not been ruled out."])
    conflicts = {str(item.get("code")) for item in commercial.get("data_conflicts") or []}
    if "delivery" in topics and "ready_status_future_delivery" in conflicts:
        lines.extend(["", "The delivery timeline is currently being verified by the Sales team."])
    lines.extend(["", "Which option would you like to explore in more detail?"])
    return "\n".join(lines)


def appointment_intent_present(
    inbound: str, history: list[dict[str, str]], *, classified_intent: str | None = None,
) -> bool:
    text = inbound or ""
    explicit_physical = bool(re.search(
        r"\b(?:in person|in-person|physically|presencial(?:mente)?)\b|"
        r"\b(?:schedule|book|arrange|agendar|programar|reservar)\b.{0,35}"
        r"\b(?:appointment|visit|tour|showing|cita|visita|recorrido)\b",
        text, re.IGNORECASE,
    ))
    if classified_intent == "request_appointment" and (explicit_physical or not VISUAL_MATERIAL_TERMS.search(text)):
        return True
    if VISUAL_MATERIAL_TERMS.search(text) and not explicit_physical:
        return False
    if APPOINTMENT_TERMS.search(text):
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
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", cleaned)).strip()


def action_types(actions: list[Any]) -> set[str]:
    return {
        str(action.get("type"))
        for action in actions
        if isinstance(action, dict) and action.get("type")
    }

