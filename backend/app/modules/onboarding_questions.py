from __future__ import annotations

import re
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
    "public_contact_emails": {
        "input_type": "multi_select",
        "examples": ["info@example.com", "sales@example.com, support@example.com"],
        "help_text": "Public-facing addresses shown to customers; these are separate from user login emails.",
    },
    "public_contact_phones": {
        "input_type": "multi_select",
        "examples": ["+1 305 555 0100", "+51 1 555 0100, +51 999 555 010"],
        "help_text": "Phone numbers the public can use to contact the company.",
    },
    "corporate_social_profiles": {
        "input_type": "multi_select",
        "examples": [
            "https://www.linkedin.com/company/example",
            "https://www.instagram.com/example",
        ],
        "help_text": "Official company profiles on LinkedIn, Instagram, Facebook, X, YouTube, TikTok, or another network.",
    },
    "legal_entity_type": {
        "input_type": "single_select",
        "options": ["Corporation", "Limited liability company", "Partnership", "Private company", "Public company"],
    },
    "dba": {
        "input_type": "conditional_text",
        "prompt": (
            "Does the company operate under a **DBA (Doing Business As)**? "
            "If yes, enter the registered trade or business name."
        ),
        "help_text": (
            "A DBA (Doing Business As) is a registered trade or business name "
            "used when it differs from the legal company name."
        ),
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


def build_next_question(
    blockers: list[dict[str, Any]],
    *,
    final_prompt: str,
    profile_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
            "help_text": None,
            "answer_actions": {},
        }
    blocker = blockers[0]
    field = blocker["field"]
    config = QUESTION_CATALOG.get(field, {})
    options = list(config.get("options", []))
    examples = list(config.get("examples", []))
    answer_actions: dict[str, dict[str, Any]] = {}
    if field == "dba":
        preferred_name = str((profile_data or {}).get("preferred_display_name") or "").strip()
        if preferred_name:
            copy_label = f"Yes — use {preferred_name}"
            options.append(copy_label)
            answer_actions[copy_label] = {
                "kind": "copy_field",
                "source_field": "preferred_display_name",
            }
        no_dba_label = "No DBA — not applicable"
        options.append(no_dba_label)
        answer_actions[no_dba_label] = {"kind": "not_applicable"}
    definition_requirement = blocker.get("requirement")
    if definition_requirement == "conditionally_required" or blocker.get("status") == "applicability_pending":
        later_label = "Provide later"
        not_applicable_label = "Not applicable"
        if later_label not in options:
            options.append(later_label)
        if not_applicable_label not in options and field != "dba":
            options.append(not_applicable_label)
        answer_actions[later_label] = {"kind": "defer"}
        answer_actions.setdefault(not_applicable_label, {"kind": "not_applicable"})
    if config.get("prompt"):
        prompt = str(config["prompt"])
    elif options:
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
        "help_text": config.get("help_text"),
        "answer_actions": answer_actions,
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
    if field == "public_contact_emails":
        values = value if isinstance(value, list) else []
        email_pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        if not values or any(not isinstance(item, str) or not email_pattern.fullmatch(item.strip()) for item in values):
            return {
                "code": "invalid_public_contact_emails",
                "field": field,
                "message": "Enter one or more valid public contact email addresses.",
            }
    if field == "public_contact_phones":
        values = value if isinstance(value, list) else []
        if not values or any(
            not isinstance(item, str) or len(re.sub(r"\D", "", item)) < 7
            for item in values
        ):
            return {
                "code": "invalid_public_contact_phones",
                "field": field,
                "message": "Enter one or more valid public phone numbers.",
            }
    if field == "corporate_social_profiles":
        values = value if isinstance(value, list) else []
        valid = all(
            isinstance(item, str)
            and (parsed := urlparse(item)).scheme in {"http", "https"}
            and bool(parsed.hostname)
            for item in values
        )
        if not values or not valid:
            return {
                "code": "invalid_social_profiles",
                "field": field,
                "message": "Enter one or more complete HTTP or HTTPS social profile URLs.",
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
