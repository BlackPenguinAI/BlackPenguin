from __future__ import annotations

import hashlib
from typing import Any, Callable


def format_user_facing_value(value: Any) -> str:
    """Render onboarding values without leaking JSON-oriented storage syntax."""
    if isinstance(value, list):
        return ", ".join(format_user_facing_value(item) for item in value) or "Not applicable"
    if isinstance(value, dict):
        if isinstance(value.get("exists"), bool) and "url" in value:
            return str(value.get("url") or "No official website")
        entries = [
            f"{str(key).replace('_', ' ').capitalize()}: {format_user_facing_value(item)}"
            for key, item in value.items()
            if item is not None
        ]
        return "; ".join(entries) if entries else "Not applicable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "Not applicable"
    return str(value)


def conversational_acknowledgement(
    *,
    accepted: list[dict[str, Any]],
    label_for: Callable[[str], str],
    next_prompt: str | None,
    first_name: str | None = None,
    scope: str = "profile",
) -> str:
    """Build stable, varied acknowledgements without adding another model call."""
    if not accepted:
        return next_prompt or ""

    normalized = []
    for item in accepted:
        field = str(item["field"])
        status = str(item.get("status") or "confirmed")
        display = "Not applicable" if status == "not_applicable" else (
            "Saved for later" if status == "deferred" else format_user_facing_value(item.get("value"))
        )
        normalized.append((field, label_for(field), display, status))

    seed = "|".join(f"{field}:{status}" for field, _, _, status in normalized)
    variant = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 4
    name = f", {first_name.strip()}" if first_name and first_name.strip() else ""

    if len(normalized) == 1:
        _, label, display, status = normalized[0]
        if status == "deferred":
            opening = f"No problem{name}. We can return to **{label}** later."
        elif status == "not_applicable":
            opening = f"Understood{name}. I marked **{label}** as not applicable."
        else:
            templates = (
                f"Perfect{name}. I've recorded **{label}** as **{display}**.",
                f"Great{name} — **{label}** is now set to **{display}**.",
                f"Thanks{name}. That clarifies **{label}**: **{display}**.",
                f"Got it{name}. I've updated **{label}** with **{display}**.",
            )
            opening = templates[variant]
    else:
        labels = ", ".join(f"**{label}**" for _, label, _, _ in normalized)
        templates = (
            f"Perfect{name}. I've incorporated the new details for {labels}.",
            f"Great{name} — the {scope} is clearer now. I updated {labels}.",
            f"Thanks{name}. I've saved the confirmed information for {labels}.",
            f"All set{name}. I updated {labels} and kept the onboarding moving.",
        )
        opening = templates[variant]

    return opening + (f"\n\n{next_prompt}" if next_prompt else "")
