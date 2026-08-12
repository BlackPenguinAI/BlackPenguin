from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


QUESTION_CATALOG: dict[str, dict[str, Any]] = {
    "official_corporate_website": {
        "input_type": "url",
        "examples": ["https://example.com", "No website"],
    },
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
        "minimum_characters": 25,
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
            "minimum_characters": None,
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
        "minimum_characters": config.get("minimum_characters"),
    }


def is_too_short(field: str, value: Any) -> bool:
    validation = validate_onboarding_value(field, value)
    return bool(validation and validation["code"] in {"minimum_words", "minimum_characters"})


def validate_onboarding_value(field: str, value: Any) -> dict[str, Any] | None:
    """Return a stable validation error shared by chat, extraction and review flows."""
    if field == "official_corporate_website":
        exists = value.get("exists") if isinstance(value, dict) else None
        url = value.get("url") if isinstance(value, dict) else None
        parsed = urlparse(url) if isinstance(url, str) else None
        valid_url = bool(parsed and parsed.scheme in {"http", "https"} and parsed.hostname)
        if exists is False and url is None:
            return None
        if exists is not True or not valid_url:
            return {
                "code": "invalid_website",
                "field": field,
                "message": "Enter a valid HTTP or HTTPS website URL, or select no official website.",
            }
    config = QUESTION_CATALOG.get(field, {})
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    minimum_words = config.get("minimum_words")
    if minimum_words and len(normalized.split()) < minimum_words:
        return {
            "code": "minimum_words",
            "field": field,
            "message": f"Enter at least {minimum_words} words.",
            "minimum_words": minimum_words,
        }
    minimum_characters = config.get("minimum_characters")
    if minimum_characters and len(normalized) < minimum_characters:
        return {
            "code": "minimum_characters",
            "field": field,
            "message": f"Enter at least {minimum_characters} characters.",
            "minimum_characters": minimum_characters,
        }
    return None
