"""Human-readable Lead presentation contract shared by Schedule and Leads."""

from __future__ import annotations

import ast
import json
from typing import Any


LABELS = {
    "selected_product": "Selected property",
    "custom_answers": "Additional answers",
    "first_name": "First name", "last_name": "Last name", "phone": "Phone", "email": "Email",
    "budget": "Budget", "minimum": "Minimum", "maximum": "Maximum", "currency": "Currency",
    "bedrooms": "Bedrooms", "bathrooms": "Bathrooms", "description": "Description", "code": "Code",
    "name": "Name", "area_min": "Minimum area", "area_max": "Maximum area", "area_unit": "Area unit",
}


def _parse(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip().startswith(("{", "[")):
        return value
    for decoder in (json.loads, ast.literal_eval):
        try:
            return decoder(value)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            pass
    return value


def _label(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").strip().capitalize())


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value).strip()


def rows(value: Any, prefix: str = "") -> list[dict[str, str]]:
    value = _parse(value)
    result: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_prefix = f"{prefix} · {_label(str(key))}" if prefix else _label(str(key))
            result.extend(rows(item, child_prefix))
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            result.extend(rows(item, f"{prefix} {index}".strip()))
    elif value not in (None, ""):
        result.append({"label": prefix or "Information", "value": _display(value)})
    return result


def lead_presentation(lead: Any, form: dict, summary: Any, objections: list[dict]) -> dict:
    selected = form.get("selected_product") or form.get("property") or {}
    budget = form.get("budget") or {
        "minimum": form.get("budget_min"), "maximum": form.get("budget_max"), "currency": form.get("currency"),
    }
    custom = form.get("custom_answers") or {}
    summary_rows = rows(summary, "Summary")
    summary_text = " · ".join(f"{item['label']}: {item['value']}" for item in summary_rows[:8])
    if not summary_text:
        useful = rows({"property": selected, "budget": budget})
        summary_text = " · ".join(f"{item['label']}: {item['value']}" for item in useful[:8]) or "Profile details will appear as the conversation progresses."
    objection_names = [str(item.get("type") or "").replace("_", " ") for item in objections if item.get("type")]
    product_name = selected.get("name") if isinstance(selected, dict) else selected
    questions = [
        "What matters most to you after seeing the property in person?",
        "Which feature would make you comfortable moving to the next step?",
        "Who else should be involved in the purchase decision?",
    ]
    if budget and rows(budget):
        questions.insert(1, "Does the confirmed budget include closing costs and any upgrades?")
    return {
        "contact": rows({"phone": lead.phone, "email": lead.email}),
        "interest": rows(selected, "Property"),
        "budget": rows(budget, "Budget"),
        "custom_answers": rows(custom),
        "summary": summary_text,
        "visit_playbook": {
            "objective": f"Validate the lead's fit for {product_name or 'the selected property'} and agree on a concrete next step.",
            "questions": questions,
            "actions": ["Review the property and budget before arrival.", "Confirm decision makers and financing readiness.", "End the visit with one agreed follow-up date and action."],
            "watch_for": objection_names or ["Unresolved timing, financing or decision-maker concerns"],
        },
    }
