from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


RESOLVED_STATUSES = {"confirmed", "corrected_by_user"}
VALID_STATUSES = {
    "missing",
    "extracted",
    "pending_confirmation",
    "confirmed",
    "corrected_by_user",
    "conflicting",
    "not_applicable",
}


@dataclass(frozen=True)
class FieldDefinition:
    key: str
    label: str
    requirement: str


REQUIRED_FIELDS = (
    FieldDefinition("official_company_name", "Official company name", "required"),
    FieldDefinition("preferred_display_name", "Preferred display name", "required"),
    FieldDefinition("official_corporate_website", "Official website or no-website confirmation", "required"),
    FieldDefinition("headquarters", "Headquarters", "required"),
    FieldDefinition("primary_business_model", "Primary business model", "required"),
    FieldDefinition("core_asset_classes", "Core company-wide asset class", "required"),
    FieldDefinition("current_operating_footprint", "Current operating footprint", "required"),
    FieldDefinition("approved_short_company_description", "Approved short company description", "required"),
    FieldDefinition("corporate_value_proposition", "Corporate value proposition or philosophy", "required"),
    FieldDefinition("corporate_differentiators", "Corporate differentiator", "required"),
)

CONDITIONAL_FIELDS = (
    FieldDefinition("legal_company_name", "Legal company name", "conditionally_required"),
    FieldDefinition("dba", "DBA (Doing Business As)", "conditionally_required"),
    FieldDefinition("parent_company", "Parent company", "conditionally_required"),
    FieldDefinition("primary_corporate_sales_contact", "Primary corporate sales contact", "conditionally_required"),
    FieldDefinition("primary_corporate_marketing_contact", "Primary corporate marketing contact", "conditionally_required"),
    FieldDefinition("additional_corporate_languages", "Additional corporate languages", "conditionally_required"),
    FieldDefinition("corporate_compliance_information", "Corporate compliance information", "conditionally_required"),
)

RECOMMENDED_FIELDS = tuple(
    FieldDefinition(key, label, "recommended")
    for key, label in (
        ("year_established", "Year established"),
        ("general_business_email", "General business email"),
        ("general_business_phone", "General business phone"),
        ("additional_offices", "Additional offices"),
        ("ceo_or_president", "CEO (Chief Executive Officer) or president"),
        ("founders", "Founder or founders"),
        ("executive_sponsor", "Executive sponsor"),
        ("head_of_development", "Head of development"),
        ("head_of_operations", "Head of operations"),
        ("secondary_business_activities", "Secondary business activities"),
        ("historical_business_activities", "Historical business activities"),
        ("secondary_asset_classes", "Secondary asset classes"),
        ("historical_asset_classes", "Historical asset classes"),
        ("historical_markets", "Historical markets"),
        ("expansion_markets", "Publicly confirmed expansion markets"),
        ("mission", "Mission"),
        ("vision", "Vision"),
        ("corporate_values", "Corporate values"),
        ("sustainability_principles", "Sustainability principles"),
        ("technology_capabilities", "Technology capabilities"),
        ("community_impact_principles", "Community-impact principles"),
        ("completed_projects_count", "Number of completed projects"),
        ("active_projects_count", "Number of active projects"),
        ("units_developed", "Units developed"),
        ("units_under_development", "Units under development"),
        ("portfolio_summary", "General portfolio summary"),
    )
)

OPTIONAL_FIELDS = tuple(
    FieldDefinition(key, label, "optional")
    for key, label in (
        ("legal_entity_type", "Legal entity type"),
        ("subsidiaries", "Subsidiaries"),
        ("ownership_structure", "Ownership structure"),
        ("assets_under_management", "Assets under management"),
        ("portfolio_valuation", "Portfolio valuation"),
        ("investment_horizon", "Investment horizon"),
        ("typical_project_size", "Typical project size"),
        ("typical_unit_count", "Typical unit count"),
        ("awards", "Awards"),
        ("certifications", "Certifications"),
        ("press_recognition", "Press recognition"),
        ("executive_biographies", "Executive biographies"),
        ("organizational_chart", "Organizational chart"),
        ("brand_book", "Brand book"),
        ("corporate_tagline", "Corporate tagline"),
        ("corporate_social_profiles", "Corporate social media profiles"),
        ("company_history", "Company history"),
        ("corporate_milestones", "Corporate milestones"),
        ("corporate_social_responsibility", "Corporate social-responsibility programs"),
    )
)

ALL_FIELDS = REQUIRED_FIELDS + CONDITIONAL_FIELDS + RECOMMENDED_FIELDS + OPTIONAL_FIELDS
FIELD_BY_KEY = {field.key: field for field in ALL_FIELDS}

# Temporary compatibility aliases for older prompts and model variations.
# Canonical snake_case keys remain the only keys persisted by the application.
FIELD_ALIASES = {
    "legal name": "official_company_name",
    "company name": "official_company_name",
    "official company name": "official_company_name",
    "display name": "preferred_display_name",
    "preferred display name": "preferred_display_name",
    "official website": "official_corporate_website",
    "corporate website": "official_corporate_website",
    "dba": "dba",
    "headquarters": "headquarters",
    "year established": "year_established",
    "business model": "primary_business_model",
    "core focus": "primary_business_model",
    "asset classes": "core_asset_classes",
    "market coverage": "current_operating_footprint",
    "operating footprint": "current_operating_footprint",
    "short company description": "approved_short_company_description",
    "value proposition": "corporate_value_proposition",
    "key differentiators": "corporate_differentiators",
    "differentiators": "corporate_differentiators",
}


def normalize_field_key(value: Any) -> str | None:
    """Return a canonical field key or ``None`` when the key is unsupported."""
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if candidate in FIELD_BY_KEY:
        return candidate

    normalized = " ".join(
        candidate.replace("_", " ").replace("-", " ").casefold().split()
    )
    return FIELD_ALIASES.get(normalized)


def _is_resolved(status: str) -> bool:
    return status in RESOLVED_STATUSES


def _count_captured(fields: Iterable[FieldDefinition], states: dict[str, Any]) -> int:
    return sum(
        1
        for field in fields
        if states.get(field.key, {}).get("status", "missing") != "missing"
    )


def calculate_completion(
    states: dict[str, Any] | None,
    *,
    final_approved: bool = False,
) -> dict[str, Any]:
    states = states or {}

    required_completed = sum(
        _is_resolved(states.get(field.key, {}).get("status", "missing"))
        for field in REQUIRED_FIELDS
    )

    applicable = []
    unevaluated = []
    for field in CONDITIONAL_FIELDS:
        field_state = states.get(field.key, {})
        if field_state.get("applicable") is True:
            applicable.append(field)
        elif field_state.get("applicable") is not False:
            unevaluated.append(field)

    conditional_completed = sum(
        _is_resolved(states.get(field.key, {}).get("status", "missing"))
        for field in applicable
    )

    required_score = 90 * required_completed / len(REQUIRED_FIELDS)
    conditional_denominator = len(applicable) + len(unevaluated)
    conditional_score = (
        10
        if conditional_denominator == 0
        else 10 * conditional_completed / conditional_denominator
    )

    blockers = []
    for field in REQUIRED_FIELDS:
        status = states.get(field.key, {}).get("status", "missing")
        if not _is_resolved(status):
            blockers.append({"field": field.key, "label": field.label, "status": status})
    for field in applicable:
        status = states.get(field.key, {}).get("status", "missing")
        if not _is_resolved(status):
            blockers.append({"field": field.key, "label": field.label, "status": status})
    for field in unevaluated:
        blockers.append({"field": field.key, "label": field.label, "status": "applicability_pending"})

    can_complete = not blockers and final_approved
    return {
        "percentage": min(100, round(required_score + conditional_score)),
        "can_complete": can_complete,
        "final_approved": final_approved,
        "required": {
            "completed": required_completed,
            "total": len(REQUIRED_FIELDS),
            "remaining": len(REQUIRED_FIELDS) - required_completed,
        },
        "conditional": {
            "total": len(CONDITIONAL_FIELDS),
            "evaluated": len(CONDITIONAL_FIELDS) - len(unevaluated),
            "applicable": len(applicable),
            "completed": conditional_completed,
            "remaining": len(applicable) - conditional_completed,
        },
        "recommended": {
            "captured": _count_captured(RECOMMENDED_FIELDS, states),
            "total": len(RECOMMENDED_FIELDS),
        },
        "optional": {
            "captured": _count_captured(OPTIONAL_FIELDS, states),
            "total": len(OPTIONAL_FIELDS),
        },
        "blockers": blockers,
    }


def field_progress(states: dict[str, Any] | None) -> list[dict[str, Any]]:
    states = states or {}
    result = []
    for definition in ALL_FIELDS:
        state = states.get(definition.key, {})
        result.append(
            {
                "key": definition.key,
                "label": definition.label,
                "requirement": definition.requirement,
                "status": state.get("status", "missing"),
                "applicable": state.get("applicable"),
            }
        )
    return result
