from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy.orm import Session

from app.modules.projects import sales_asset_service
from app.modules.projects.models import (
    Project,
    ProjectPropertyType,
    ProjectUnit,
)


CONFIRMED_STATUSES = {"confirmed", "corrected_by_user"}
AVAILABLE_UNIT_STATUSES = {"available", "active", "ready"}


def _bedroom_signature(value: Any) -> str | None:
    text = str(value or "").casefold()
    if re.search(r"\b4\s*\+|\b4(?:br|\s*bed)", text):
        return "4+"
    match = re.search(r"\b([0-3])(?:br|\s*bed)", text)
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    return float(value) if value is not None else None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def confirmed_profile_facts(profile: Any) -> dict[str, Any]:
    """Return only affirmative, administrator-confirmed Project facts.

    ``not_applicable`` and ``deferred`` are completion states, not commercial
    facts. Exposing their stale values to the model can turn a field that was
    intentionally disabled into a customer-facing claim.
    """
    if not profile:
        return {}
    states = profile.field_states or {}
    return {
        key: value
        for key, value in (profile.profile_data or {}).items()
        if states.get(key, {}).get("status") in CONFIRMED_STATUSES
        and states.get(key, {}).get("applicable", True) is not False
    }


def _property_type_payload(item: ProjectPropertyType) -> dict[str, Any]:
    return {
        "id": item.id,
        "property_type": item.name,
        "description": item.description,
        "bedrooms": item.bedrooms,
        "bathrooms": item.bathrooms,
        "area_min": _number(item.area_min),
        "area_max": _number(item.area_max),
        "area_unit": item.area_unit,
        "total_units": item.total_units,
        "available_units": item.available_units,
        "starting_price": _number(item.starting_price),
        "maximum_price": _number(item.maximum_price),
        "currency": item.currency,
        "features": item.features or [],
        "inventory_updated_at": _iso(item.inventory_updated_at),
    }


def _unit_payload(unit: ProjectUnit) -> dict[str, Any]:
    return {
        "id": unit.id,
        "unit_code": unit.unit_code,
        "property_type": unit.typology,
        "phase_or_tower": unit.tower_or_phase,
        "area": _number(unit.area),
        "bedrooms": unit.bedrooms,
        "bathrooms": unit.bathrooms,
        "price": _number(unit.list_price),
        "currency": unit.currency,
        "status": unit.status,
        "inventory_updated_at": _iso(unit.inventory_updated_at),
    }


def _catalog_conflicts(
    facts: dict[str, Any], property_types: list[ProjectPropertyType], units: list[ProjectUnit],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if units:
        available_units = sum(
            str(unit.status or "").casefold() in AVAILABLE_UNIT_STATUSES for unit in units
        )
        recorded = facts.get("available_inventory")
        try:
            recorded_count = int(recorded) if recorded not in (None, "") else None
        except (TypeError, ValueError):
            recorded_count = None
        if recorded_count is not None and recorded_count != available_units:
            conflicts.append({
                "code": "inventory_count_mismatch",
                "profile_value": recorded_count,
                "canonical_value": available_units,
                "resolution": "Individual unit inventory takes precedence.",
            })
    catalog_names = {item.name.casefold() for item in property_types}
    catalog_bedrooms = {
        signature for item in property_types
        if (signature := _bedroom_signature(item.name)) is not None
    }
    raw_typologies = facts.get("typologies") or []
    if isinstance(raw_typologies, str):
        raw_typologies = [part.strip() for part in raw_typologies.split(",") if part.strip()]
    missing = [
        str(value) for value in raw_typologies
        if str(value).strip()
        and str(value).casefold() not in catalog_names
        and (
            (signature := _bedroom_signature(value)) is not None
            and signature not in catalog_bedrooms
        )
    ]
    if property_types and missing:
        conflicts.append({
            "code": "profile_typology_missing_from_catalog",
            "values": missing,
            "resolution": "Do not offer these typologies until the catalog is corrected.",
        })
    return conflicts


def build_commercial_context(
    db: Session, *, project: Project, company_id: str, lead_id: str, channel: str = "sms",
) -> dict[str, Any]:
    """Build the one customer-facing commercial source of truth for a turn."""
    facts = confirmed_profile_facts(project.profile)
    property_types = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status == "confirmed",
    ).order_by(ProjectPropertyType.sort_order, ProjectPropertyType.created_at).all()
    units = db.query(ProjectUnit).filter(ProjectUnit.project_id == project.id).all()

    # Give the model identifiers and customer-facing metadata only. A link is
    # minted later by the deterministic action executor, never while context is
    # loaded and never for an unapproved onboarding source.
    assets = [
        {
            "asset_id": item.id,
            "asset_type": item.asset_type,
            "property_type": item.property_type.name if item.property_type else None,
            "name": item.display_name,
            "description": item.description,
            "mime_type": item.source.mime_type if item.source else None,
            "version": item.version,
            "valid_until": _iso(item.valid_until),
            "allowed_channels": item.allowed_channels or [],
        }
        for item in sales_asset_service.approved_for_turn(
            db, project_id=project.id, company_id=company_id, channel=channel,
        )
    ]

    latest_values = [
        value for value in [
            *(unit.inventory_updated_at for unit in units),
            *(item.inventory_updated_at for item in property_types),
        ] if value is not None
    ]
    latest = max(latest_values) if latest_values else None
    inventory_source = "individual_units" if units else "property_type_catalog"
    inventory = (
        [_unit_payload(unit) for unit in units]
        if units else [_property_type_payload(item) for item in property_types]
    )
    return {
        "confirmed_project_facts": facts,
        "property_types": [_property_type_payload(item) for item in property_types],
        "inventory": inventory,
        "inventory_source": inventory_source,
        "inventory_updated_at": _iso(latest),
        "available_assets": assets,
        "data_conflicts": _catalog_conflicts(facts, property_types, units),
    }

