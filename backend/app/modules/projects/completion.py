from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.onboarding_contract import field_approved, field_resolved


RESOLVED_STATUSES = {"confirmed", "corrected_by_user", "not_applicable", "deferred"}
VALID_STATUSES = {
    "missing", "extracted", "pending_confirmation", "confirmed",
    "corrected_by_user", "conflicting", "stale", "expired", "not_applicable",
    "deferred",
}

# These steps can be postponed without withholding approval of the commercial
# profile. They still do not authorize messaging, scheduling or Meta ingestion.
DEFERRABLE_PROFILE_FIELDS = {"project_cover", "sales_contacts", "appointment_routing", "campaigns_defined", "meta_connection_verified"}


@dataclass(frozen=True)
class FieldDefinition:
    key: str
    label: str
    section: str
    requirement: str = "required"


FIELDS = (
    FieldDefinition("project_name", "Project name", "identity"),
    FieldDefinition("project_type", "Project type", "identity"),
    FieldDefinition("project_status", "Development status", "identity"),
    FieldDefinition("short_description", "Approved short description", "identity"),
    FieldDefinition("project_cover", "Project cover image", "media"),
    FieldDefinition("exact_address", "Exact address", "location"),
    FieldDefinition("city", "City / region", "location"),
    FieldDefinition("country", "Country", "location"),
    FieldDefinition("location_references", "Location references", "location", "recommended"),
    FieldDefinition("phases_and_towers", "Phases and towers", "structure", "conditionally_required"),
    FieldDefinition("property_type_catalog", "Confirmed property type catalog", "product"),
    FieldDefinition("typologies", "Unit typologies", "product"),
    FieldDefinition("areas", "Area ranges", "product"),
    FieldDefinition("bedrooms_and_bathrooms", "Bedrooms and bathrooms", "product"),
    FieldDefinition("construction_details", "Construction details", "product", "recommended"),
    FieldDefinition("amenities", "Amenities", "amenities"),
    FieldDefinition("parking_and_storage", "Parking and storage", "amenities", "conditionally_required"),
    FieldDefinition("currency", "Commercial currency", "commercial"),
    FieldDefinition("starting_price", "Starting price", "commercial"),
    FieldDefinition("payment_methods", "Payment methods", "commercial"),
    FieldDefinition("promotions", "Current promotions", "commercial", "conditionally_required"),
    FieldDefinition("delivery_dates", "Delivery dates", "commercial"),
    FieldDefinition("available_inventory", "Available inventory", "inventory"),
    FieldDefinition("sales_authorization", "Authorization for AI (Artificial Intelligence)-assisted sales", "inventory"),
    FieldDefinition("target_audience", "Target audience", "sales_strategy"),
    FieldDefinition("value_proposition", "Project value proposition", "sales_strategy"),
    FieldDefinition("key_differentiators", "Key differentiators", "sales_strategy"),
    FieldDefinition("qualification_rules", "Lead qualification rules", "sales_strategy"),
    FieldDefinition("sales_contacts", "Assigned Sales team", "routing"),
    FieldDefinition("appointment_routing", "Automatic lead distribution", "routing"),
    FieldDefinition("campaigns_defined", "Meta Lead Ads setup", "campaigns"),
    FieldDefinition("meta_connection_verified", "Meta connection verified", "campaigns", "conditionally_required"),
    FieldDefinition("compliance_notes", "Project compliance notes", "approval", "conditionally_required"),
)

FIELD_BY_KEY = {field.key: field for field in FIELDS}
SECTIONS = (
    ("identity", "Project Identity"), ("location", "Location"),
    ("media", "Project Media"),
    ("structure", "Development Structure"), ("product", "Product Details"),
    ("amenities", "Amenities"), ("commercial", "Commercial Offer"),
    ("inventory", "Inventory"), ("sales_strategy", "Sales Strategy"),
    ("routing", "Team & Routing"), ("campaigns", "Campaigns & Meta"),
    ("approval", "Final Approval"),
)

ALIASES = {
    "name": "project_name", "project name": "project_name", "type": "project_type",
    "status": "project_status", "description": "short_description", "address": "exact_address",
    "price from": "starting_price", "price": "starting_price", "available units": "available_inventory",
    "inventory": "available_inventory", "sales phases": "phases_and_towers",
}


def normalize_field_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in FIELD_BY_KEY:
        return candidate
    normalized = " ".join(candidate.replace("_", " ").replace("-", " ").casefold().split())
    return ALIASES.get(normalized)


def calculate_completion(states: dict[str, Any] | None, *, final_approved: bool = False) -> dict[str, Any]:
    states = states or {}
    required = [f for f in FIELDS if f.requirement == "required"]
    conditional = [f for f in FIELDS if f.requirement == "conditionally_required"]
    applicable_conditional = [
        f for f in conditional if states.get(f.key, {}).get("applicable") is True
    ]
    unevaluated_conditional = [
        f for f in conditional if states.get(f.key, {}).get("applicable") is None
    ]
    applicable = required + applicable_conditional
    completed = [f for f in applicable if field_resolved(
        states.get(f.key), allow_deferred=f.key in DEFERRABLE_PROFILE_FIELDS or f.requirement != "required",
    )]
    blockers = [
        {
            "field": f.key,
            "label": f.label,
            "section": f.section,
            "status": states.get(f.key, {}).get("status", "missing"),
            "requirement": f.requirement,
        }
        for f in applicable if f not in completed
    ]
    blockers.extend({
        "field": f.key,
        "label": f.label,
        "section": f.section,
        "status": "applicability_pending",
        "requirement": f.requirement,
    } for f in unevaluated_conditional)
    denominator = len(applicable) + len(unevaluated_conditional)
    percentage = round(100 * len(completed) / denominator) if denominator else 100
    sections = []
    for key, label in SECTIONS:
        section_fields = [
            f for f in FIELDS
            if f.section == key and (f in applicable or f in unevaluated_conditional)
        ]
        section_completed = [f for f in section_fields if f in completed]
        sections.append({
            "key": key, "label": label, "completed": len(section_completed),
            "total": len(section_fields),
            "percentage": round(100 * len(section_completed) / len(section_fields)) if section_fields else 100,
        })
    activation_fields = [
        f for f in FIELDS
        if f.section in {"inventory", "routing", "campaigns", "approval"}
        and (f.requirement == "required" or states.get(f.key, {}).get("applicable") is True)
    ]
    activation_blockers = [
        {
            "field": f.key,
            "label": f.label,
            "section": f.section,
            "status": states.get(f.key, {}).get("status", "missing"),
            "requirement": f.requirement,
        }
        for f in activation_fields
        if not field_approved(states.get(f.key))
    ]
    def capability(fields):
        pending = [{"field": key, "label": FIELD_BY_KEY[key].label,
                    "status": states.get(key, {}).get("status", "missing")}
                   for key in fields if not field_approved(states.get(key))]
        if not final_approved:
            pending.append({"field": "final_approval", "label": "Final profile approval", "status": "pending"})
        if blockers:
            pending.append({"field": "profile_requirements", "label": "Required profile facts", "status": "pending"})
        return {"ready": not pending, "blockers": pending}
    capabilities = {
        "manual_messaging": capability(["sales_authorization"]),
        "appointments": capability(["sales_authorization", "sales_contacts", "appointment_routing"]),
        "meta_lead_ads": capability(["sales_authorization", "campaigns_defined", "meta_connection_verified"]),
    }
    return {
        "percentage": percentage,
        "required_fields_complete": not blockers,
        "ready_for_confirmation": not blockers and not final_approved,
        "can_complete": not blockers and final_approved,
        "final_approved": final_approved,
        "completed": len(completed), "total": denominator, "remaining": len(blockers),
        "sections": sections, "blockers": blockers,
        "sales_activation_status": "ready" if not activation_blockers and final_approved else "not_ready",
        "sales_activation_blockers": activation_blockers,
        "capabilities": capabilities,
    }


def field_progress(states: dict[str, Any] | None) -> list[dict[str, Any]]:
    states = states or {}
    return [
        {
            "key": field.key, "label": field.label, "section": field.section,
            "requirement": field.requirement,
            "status": states.get(field.key, {}).get("status", "missing"),
            "applicable": states.get(field.key, {}).get("applicable"),
        }
        for field in FIELDS
    ]
