from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Project, ProjectOnboardingSource, ProjectSalesAsset, ProjectSourceStatus


ASSET_TYPES = {
    "brochure", "floor_plan", "unit_sheet", "price_list", "amenities",
    "location_map", "legal_disclaimer", "other",
}
CHANNELS = {"sms", "whatsapp"}


def serialize(item: ProjectSalesAsset) -> dict[str, Any]:
    source = item.source
    return {
        "id": item.id,
        "company_id": item.company_id,
        "project_id": item.project_id,
        "property_type_id": item.property_type_id,
        "source_id": item.source_id,
        "asset_type": item.asset_type,
        "display_name": item.display_name,
        "description": item.description,
        "approval_status": item.approval_status,
        "version": item.version,
        "valid_from": item.valid_from,
        "valid_until": item.valid_until,
        "allowed_channels": item.allowed_channels or [],
        "approved_by_user_id": item.approved_by_user_id,
        "approved_at": item.approved_at,
        "source_name": source.original_filename or source.name if source else None,
        "mime_type": source.mime_type if source else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def list_for_project(db: Session, project: Project, *, include_archived: bool = False) -> list[ProjectSalesAsset]:
    query = db.query(ProjectSalesAsset).filter(
        ProjectSalesAsset.project_id == project.id,
        ProjectSalesAsset.company_id == project.company_id,
    )
    if not include_archived:
        query = query.filter(ProjectSalesAsset.approval_status != "archived")
    return query.order_by(ProjectSalesAsset.updated_at.desc()).all()


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(payload.get("asset_type") or "").strip()
    if asset_type not in ASSET_TYPES:
        raise HTTPException(status_code=422, detail="Select a supported sales material type.")
    name = str(payload.get("display_name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a customer-facing material name.")
    channels = list(dict.fromkeys(payload.get("allowed_channels") or []))
    if not channels or any(channel not in CHANNELS for channel in channels):
        raise HTTPException(status_code=422, detail="Select SMS, WhatsApp, or both channels.")
    valid_from = payload.get("valid_from")
    valid_until = payload.get("valid_until")
    if valid_from and valid_until and valid_until <= valid_from:
        raise HTTPException(status_code=422, detail="The material expiration must be after its start date.")
    return {**payload, "asset_type": asset_type, "display_name": name, "allowed_channels": channels}


def create(db: Session, project: Project, payload: dict[str, Any], *, user_id: str) -> ProjectSalesAsset:
    values = _validate_payload(payload)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == values.pop("source_id"),
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.status == ProjectSourceStatus.READY,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).first()
    if not source:
        raise HTTPException(status_code=422, detail="Choose a processed Project file.")
    duplicate = db.query(ProjectSalesAsset).filter(
        ProjectSalesAsset.project_id == project.id,
        ProjectSalesAsset.source_id == source.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="This file is already registered as sales material.")
    property_type_id = values.get("property_type_id")
    if property_type_id and not any(item.id == property_type_id for item in project.property_types):
        raise HTTPException(status_code=404, detail="Property type not found in this Project.")
    item = ProjectSalesAsset(
        company_id=project.company_id,
        project_id=project.id,
        source_id=source.id,
        created_by_user_id=user_id,
        approval_status="draft",
        **values,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update(db: Session, item: ProjectSalesAsset, payload: dict[str, Any]) -> ProjectSalesAsset:
    values = _validate_payload(payload)
    for key, value in values.items():
        if key != "source_id":
            setattr(item, key, value)
    item.version += 1
    # Any content or targeting change requires a fresh explicit approval.
    item.approval_status = "draft"
    item.approved_by_user_id = None
    item.approved_at = None
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def approve(db: Session, item: ProjectSalesAsset, *, user_id: str) -> ProjectSalesAsset:
    source = item.source
    if not source or source.status != ProjectSourceStatus.READY or not source.storage_path:
        raise HTTPException(status_code=409, detail="The source file is not ready for sharing.")
    now = datetime.utcnow()
    if item.valid_until and item.valid_until <= now:
        raise HTTPException(status_code=409, detail="Expired material cannot be approved.")
    item.approval_status = "approved"
    item.approved_by_user_id = user_id
    item.approved_at = now
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def archive(db: Session, item: ProjectSalesAsset) -> None:
    item.approval_status = "archived"
    item.approved_by_user_id = None
    item.approved_at = None
    db.add(item)
    db.commit()


def approved_for_turn(
    db: Session, *, project_id: str, company_id: str, channel: str,
) -> list[ProjectSalesAsset]:
    now = datetime.utcnow()
    rows = db.query(ProjectSalesAsset).join(
        ProjectOnboardingSource, ProjectOnboardingSource.id == ProjectSalesAsset.source_id,
    ).filter(
        ProjectSalesAsset.project_id == project_id,
        ProjectSalesAsset.company_id == company_id,
        ProjectSalesAsset.approval_status == "approved",
        ProjectSalesAsset.approved_at.isnot(None),
        (ProjectSalesAsset.valid_from.is_(None) | (ProjectSalesAsset.valid_from <= now)),
        (ProjectSalesAsset.valid_until.is_(None) | (ProjectSalesAsset.valid_until > now)),
        ProjectOnboardingSource.status == ProjectSourceStatus.READY,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).all()
    return [item for item in rows if channel in (item.allowed_channels or [])]
