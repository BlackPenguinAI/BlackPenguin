from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.companies.models import Company

from . import services
from .models import (
    Project,
    ProjectOnboardingSource,
    ProjectPropertyType,
    ProjectPropertyTypeMedia,
    ProjectSourceKind,
    ProjectSourceStatus,
)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def is_complete(item: ProjectPropertyType) -> bool:
    return (
        item.review_status == "confirmed"
        and item.available_units is not None
        and item.available_units >= 0
        and item.starting_price is not None
        and item.starting_price >= 0
        and bool(item.currency)
        and item.inventory_updated_at is not None
    )


def property_type_limit(db: Session, project: Project) -> int:
    company = db.query(Company).filter(Company.id == project.company_id).first()
    return int(getattr(company.plan, "max_property_types_per_project", 20) or 20) if company and company.plan else 20


def serialize(item: ProjectPropertyType) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "name": item.name,
        "code": item.code,
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
        "inventory_updated_at": item.inventory_updated_at,
        "images_status": item.images_status,
        "review_status": item.review_status,
        "source_reference": item.source_reference,
        "sort_order": item.sort_order,
        "is_complete": is_complete(item),
        "media": [
            {
                "id": media.id,
                "source_id": media.source_id,
                "caption": media.caption,
                "sort_order": media.sort_order,
                "image_url": f"/api/v1/projects/{item.project_id}/sources/{media.source_id}/file",
            }
            for media in sorted(item.media, key=lambda value: (value.sort_order, value.created_at))
        ],
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def catalog(db: Session, project: Project) -> dict[str, Any]:
    items = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status != "rejected",
    ).order_by(ProjectPropertyType.sort_order, ProjectPropertyType.created_at).all()
    confirmed = [item for item in items if item.review_status == "confirmed"]
    profile = services.get_profile(project)
    limit = property_type_limit(db, project)
    return {
        "items": [serialize(item) for item in items],
        "confirmed_count": len(confirmed),
        "candidate_count": sum(item.review_status == "candidate" for item in items),
        "limit": limit,
        "remaining": max(0, limit - len(confirmed)),
        "catalog_complete": (
            bool(confirmed)
            and all(is_complete(item) for item in confirmed)
            and not any(item.review_status == "candidate" for item in items)
            and (profile.field_states or {}).get("property_type_catalog", {}).get("status") in {"confirmed", "corrected_by_user"}
        ),
    }


def _validate_confirmation(db: Session, project: Project, item: ProjectPropertyType) -> None:
    confirmed_count = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status == "confirmed",
        ProjectPropertyType.id != item.id,
    ).count()
    limit = property_type_limit(db, project)
    if confirmed_count >= limit:
        raise HTTPException(status_code=409, detail={
            "message": f"Your plan supports {limit} confirmed property types per Project.",
            "limit": limit,
            "confirmed": confirmed_count,
        })
    if not is_complete(item):
        raise HTTPException(status_code=422, detail=(
            "A confirmed property type requires price, currency, available units, and an inventory update date."
        ))


def _sync_profile(db: Session, project: Project) -> None:
    confirmed = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status == "confirmed",
    ).all()
    profile = services.get_profile(project)
    data = dict(profile.profile_data or {})
    states = dict(profile.field_states or {})
    if not confirmed:
        data.pop("property_type_catalog", None)
        states["property_type_catalog"] = {"status": "missing", "applicable": True}
        profile.profile_data = data
        profile.field_states = states
        profile.inventory_last_updated_at = None
        flag_modified(profile, "profile_data")
        flag_modified(profile, "field_states")
        services.refresh_completion(profile)
        db.add(profile)
        return
    has_candidates = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status == "candidate",
    ).first() is not None
    data.update({
        "typologies": [item.name for item in confirmed],
        "available_inventory": sum(item.available_units or 0 for item in confirmed),
        "starting_price": min(float(item.starting_price) for item in confirmed if item.starting_price is not None),
        "currency": next((item.currency for item in confirmed if item.currency), None),
        "inventory_updated_at": max(item.inventory_updated_at for item in confirmed if item.inventory_updated_at).isoformat(),
        "areas": [
            {"type": item.name, "min": _number(item.area_min), "max": _number(item.area_max), "unit": item.area_unit}
            for item in confirmed if item.area_min is not None or item.area_max is not None
        ],
        "bedrooms_and_bathrooms": [
            {"type": item.name, "bedrooms": item.bedrooms, "bathrooms": item.bathrooms}
            for item in confirmed if item.bedrooms is not None or item.bathrooms is not None
        ],
    })
    data["property_type_catalog"] = [item.id for item in confirmed]
    for key in ("typologies", "available_inventory", "starting_price", "currency", "inventory_updated_at"):
        states[key] = {"status": "confirmed", "applicable": True}
    current_catalog_status = states.get("property_type_catalog", {}).get("status")
    if has_candidates or current_catalog_status not in {"confirmed", "corrected_by_user"}:
        states["property_type_catalog"] = {"status": "pending_confirmation", "applicable": True}
    if data["areas"]:
        states["areas"] = {"status": "confirmed", "applicable": True}
    if data["bedrooms_and_bathrooms"]:
        states["bedrooms_and_bathrooms"] = {"status": "confirmed", "applicable": True}
    profile.profile_data = data
    profile.field_states = states
    profile.inventory_last_updated_at = max(item.inventory_updated_at for item in confirmed if item.inventory_updated_at)
    flag_modified(profile, "profile_data")
    flag_modified(profile, "field_states")
    services.refresh_completion(profile)
    db.add(profile)


def confirm_catalog(db: Session, project: Project) -> dict[str, Any]:
    items = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status != "rejected",
    ).all()
    confirmed = [item for item in items if item.review_status == "confirmed"]
    if not confirmed:
        raise HTTPException(status_code=422, detail="Add and confirm at least one property type before completing the catalog.")
    if any(item.review_status == "candidate" for item in items):
        raise HTTPException(status_code=409, detail="Review or remove every extracted candidate before completing the catalog.")
    if any(not is_complete(item) for item in confirmed):
        raise HTTPException(status_code=422, detail="Complete price, currency, availability, and inventory date for every property type.")

    profile = services.get_profile(project)
    states = dict(profile.field_states or {})
    states["property_type_catalog"] = {"status": "confirmed", "applicable": True}
    profile.field_states = states
    flag_modified(profile, "field_states")
    services.refresh_completion(profile)
    db.add(profile)
    db.commit()
    return catalog(db, project)


def create(db: Session, project: Project, payload: dict[str, Any], *, user_id: str) -> ProjectPropertyType:
    item = ProjectPropertyType(project_id=project.id, created_by_user_id=user_id, updated_by_user_id=user_id, **payload)
    if item.review_status == "confirmed":
        _validate_confirmation(db, project, item)
    db.add(item)
    db.flush()
    _sync_profile(db, project)
    db.commit()
    db.refresh(item)
    return item


def update(db: Session, project: Project, item: ProjectPropertyType, payload: dict[str, Any], *, user_id: str) -> ProjectPropertyType:
    for key, value in payload.items():
        setattr(item, key, value)
    item.updated_by_user_id = user_id
    if item.review_status == "confirmed":
        _validate_confirmation(db, project, item)
    db.add(item)
    db.flush()
    _sync_profile(db, project)
    db.commit()
    db.refresh(item)
    return item


def attach_media(db: Session, project: Project, item: ProjectPropertyType, source_ids: list[str]) -> ProjectPropertyType:
    sources = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.id.in_(source_ids),
        ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE,
        ProjectOnboardingSource.status == ProjectSourceStatus.READY,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).all()
    if len({source.id for source in sources}) != len(set(source_ids)):
        raise HTTPException(status_code=422, detail="Every selected image must be a ready image from this Project.")
    existing = {media.source_id for media in item.media}
    for index, source_id in enumerate(source_ids):
        if source_id not in existing:
            db.add(ProjectPropertyTypeMedia(property_type_id=item.id, source_id=source_id, sort_order=len(existing) + index))
    item.images_status = "provided"
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
