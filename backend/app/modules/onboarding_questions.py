from __future__ import annotations

from typing import Any


QUESTION_CATALOG: dict[str, dict[str, Any]] = {
    "primary_business_model": {
        "input_type": "single_select",
        "options": ["Real-estate development", "Investment and ownership", "Asset management", "Construction", "Brokerage", "Mixed model"],
    },
    "core_asset_classes": {
        "input_type": "multi_select",
        "options": ["Condominiums", "Multifamily", "Single-family", "Mixed-use", "Hospitality", "Office", "Retail", "Industrial"],
    },
    "additional_corporate_languages": {
        "input_type": "multi_select",
        "options": ["English", "Spanish", "Portuguese", "French"],
    },
    "legal_entity_type": {
        "input_type": "single_select",
        "options": ["Corporation", "Limited liability company", "Partnership", "Private company", "Public company"],
    },
    "approved_short_company_description": {
        "input_type": "long_text",
        "examples": [
            "A real-estate developer focused on thoughtfully designed residential communities in high-growth urban markets.",
            "An integrated property company that develops, owns, and operates distinctive mixed-use destinations.",
        ],
        "minimum_words": 8,
    },
    "corporate_value_proposition": {
        "input_type": "long_text",
        "examples": [
            "We combine local market knowledge, disciplined execution, and enduring design to create long-term value.",
            "We deliver dependable development expertise from site selection through sales and operations.",
        ],
        "minimum_words": 6,
    },
    "corporate_differentiators": {
        "input_type": "long_text",
        "examples": ["Integrated development capabilities", "Local market expertise", "Design-led execution", "Proven delivery record"],
    },
    "project_type": {
        "input_type": "single_select",
        "options": ["Condominium", "Multifamily rental", "Single-family", "Mixed-use", "Hospitality", "Office", "Retail", "Industrial"],
    },
    "project_status": {
        "input_type": "single_select",
        "options": ["Planning", "Pre-construction", "Under construction", "Pre-sales", "Ready for occupancy", "Completed"],
    },
    "short_description": {
        "input_type": "long_text",
        "examples": [
            "Luxury residences combining contemporary design, premium amenities, and a central urban location.",
            "A landmark residential development designed for privacy, comfort, and elevated everyday living.",
            "Modern homes with thoughtful layouts, exceptional services, and convenient access to the city.",
        ],
        "minimum_words": 8,
    },
    "typologies": {
        "input_type": "multi_select",
        "options": ["Studio", "1 bedroom", "2 bedrooms", "3 bedrooms", "4+ bedrooms", "Penthouse", "Townhouse"],
    },
    "bedrooms_and_bathrooms": {
        "input_type": "multi_select",
        "options": ["Studio / 1 bath", "1 bed / 1 bath", "2 bed / 2 bath", "3 bed / 2+ bath", "4+ bed / 3+ bath"],
    },
    "currency": {
        "input_type": "single_select",
        "options": ["USD", "PEN", "EUR", "MXN", "COP", "BRL"],
    },
    "payment_methods": {
        "input_type": "multi_select",
        "options": ["Cash", "Bank financing", "Developer financing", "Installment plan", "Reservation deposit"],
    },
    "sales_authorization": {
        "input_type": "single_select",
        "options": ["Authorized", "Not yet authorized", "Human approval required per lead"],
    },
    "appointment_routing": {
        "input_type": "single_select",
        "options": ["Round robin", "By availability", "By project specialist", "Manual assignment"],
    },
    "campaigns_defined": {
        "input_type": "single_select",
        "options": ["Yes, configure now", "Yes, configure later", "No campaigns yet", "Not applicable"],
    },
}


def build_next_question(blockers: list[dict[str, Any]], *, final_prompt: str) -> dict[str, Any]:
    if not blockers:
        return {
            "field": None,
            "label": "Final approval",
            "prompt": final_prompt,
            "input_type": "boolean",
            "options": ["Approve profile", "I need to make changes"],
            "examples": [],
            "allow_custom": True,
            "minimum_words": None,
        }
    blocker = blockers[0]
    field = blocker["field"]
    config = QUESTION_CATALOG.get(field, {})
    options = list(config.get("options", []))
    examples = list(config.get("examples", []))
    if options:
        prompt = f"Choose the best option for **{blocker['label']}**, or suggest a different answer."
    elif examples:
        prompt = f"Choose, edit, or write a complete answer for **{blocker['label']}**."
    else:
        prompt = f"What should I record for **{blocker['label']}**?"
    return {
        "field": field,
        "label": blocker["label"],
        "prompt": prompt,
        "input_type": config.get("input_type", "text"),
        "options": options,
        "examples": examples,
        "allow_custom": True,
        "minimum_words": config.get("minimum_words"),
    }


def is_too_short(field: str, value: Any) -> bool:
    minimum = QUESTION_CATALOG.get(field, {}).get("minimum_words")
    return bool(minimum and isinstance(value, str) and len(value.split()) < minimum)
