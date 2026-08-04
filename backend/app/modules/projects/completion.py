from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RESOLVED_STATUSES = {"confirmed", "corrected_by_user", "not_applicable"}
VALID_STATUSES = {
    "missing", "extracted", "pending_confirmation", "confirmed",
    "corrected_by_user", "conflicting", "stale", "expired", "not_applicable",
}


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
    FieldDefinition("exact_address", "Exact address", "location"),
    FieldDefinition("city", "City / region", "location"),
    FieldDefinition("country", "Country", "location"),
    FieldDefinition("location_references", "Location references", "location", "recommended"),
    FieldDefinition("phases_and_towers", "Phases and towers", "structure", "conditionally_required"),
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
    FieldDefinition("inventory_updated_at", "Inventory last updated", "inventory"),
    FieldDefinition("sales_authorization", "Authorization for AI-assisted sales", "inventory"),
    FieldDefinition("target_audience", "Target audience", "sales_strategy"),
    FieldDefinition("value_proposition", "Project value proposition", "sales_strategy"),
    FieldDefinition("key_differentiators", "Key differentiators", "sales_strategy"),
    FieldDefinition("qualification_rules", "Lead qualification rules", "sales_strategy"),
    FieldDefinition("sales_contacts", "Sales contacts", "routing"),
    FieldDefinition("appointment_routing", "Appointment routing", "routing"),
    FieldDefinition("campaigns_defined", "Associated campaigns", "campaigns"),
    FieldDefinition("meta_connection_verified", "Meta connection verified", "campaigns", "conditionally_required"),
    FieldDefinition("compliance_notes", "Project compliance notes", "approval", "conditionally_required"),
)

FIELD_BY_KEY = {field.key: field for field in FIELDS}
SECTIONS = (
    ("identity", "Project Identity"), ("location", "Location"),
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
    blocking = [f for f in FIELDS if f.requirement in {"required", "conditionally_required"}]
    applicable = [
        f for f in blocking
        if f.requirement == "required" or states.get(f.key, {}).get("applicable") is not False
    ]
    completed = [f for f in applicable if states.get(f.key, {}).get("status", "missing") in RESOLVED_STATUSES]
    blockers = [
        {"field": f.key, "label": f.label, "section": f.section,
         "status": states.get(f.key, {}).get("status", "missing")}
        for f in applicable if f not in completed
    ]
    percentage = round(100 * len(completed) / len(applicable)) if applicable else 100
    sections = []
    for key, label in SECTIONS:
        section_fields = [f for f in FIELDS if f.section == key and f in applicable]
        section_completed = [f for f in section_fields if f in completed]
        sections.append({
            "key": key, "label": label, "completed": len(section_completed),
            "total": len(section_fields),
            "percentage": round(100 * len(section_completed) / len(section_fields)) if section_fields else 100,
        })
    activation_blockers = [b for b in blockers if b["section"] in {"inventory", "routing", "campaigns", "approval"}]
    return {
        "percentage": percentage,
        "required_fields_complete": not blockers,
        "ready_for_confirmation": not blockers and not final_approved,
        "can_complete": not blockers and final_approved,
        "final_approved": final_approved,
        "completed": len(completed), "total": len(applicable), "remaining": len(blockers),
        "sections": sections, "blockers": blockers,
        "sales_activation_status": "ready" if not activation_blockers and final_approved else "not_ready",
        "sales_activation_blockers": activation_blockers,
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
