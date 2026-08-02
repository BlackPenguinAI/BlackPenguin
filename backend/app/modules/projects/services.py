from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.companies.models import Company

from .completion import FIELD_BY_KEY, VALID_STATUSES, calculate_completion, field_progress, normalize_field_key
from . import storage_service
from .models import (
    Project, ProjectCampaign, ProjectMessage, ProjectOnboardingSource, ProjectProfile,
    ProjectSession, SenderType,
)


@dataclass
class ApplyUpdatesResult:
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


def check_project_limits(db: Session, company_id: str) -> None:
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.plan:
        raise HTTPException(status_code=400, detail="The company does not have an assigned plan.")
    current_count = db.query(Project).filter(
        Project.company_id == company_id, Project.is_active.is_(True)
    ).count()
    if current_count >= company.plan.max_projects:
        raise HTTPException(status_code=400, detail=f"Your plan allows {company.plan.max_projects} projects.")


def get_project(db: Session, project_id: str, company_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def create_project_with_onboarding(db: Session, *, company_id: str, payload: dict[str, Any]) -> Project:
    project = Project(**payload, company_id=company_id, is_active=True)
    db.add(project)
    db.flush()
    profile = ProjectProfile(project_id=project.id)
    session = ProjectSession(project_id=project.id)
    db.add_all([profile, session])
    seed = {
        "project_name": project.name, "short_description": project.description,
        "exact_address": project.address, "city": project.city, "country": project.country,
    }
    profile.profile_data = {key: value for key, value in seed.items() if value not in (None, "")}
    profile.field_states = {
        key: {"status": "confirmed", "applicable": True}
        for key, value in seed.items() if value not in (None, "")
    }
    refresh_completion(profile)
    db.commit()
    db.refresh(project)
    return project


def get_profile(project: Project) -> ProjectProfile:
    if not project.profile:
        raise HTTPException(status_code=500, detail="Project profile is missing.")
    seed_legacy_values(project.profile)
    return project.profile


def seed_legacy_values(profile: ProjectProfile) -> None:
    mapping = {
        "typologies": "typologies", "amenities": "amenities", "construction_details": "construction_details",
        "price_from": "starting_price", "payment_methods": "payment_methods", "discounts": "promotions",
        "delivery_dates": "delivery_dates", "available_units": "available_inventory", "sales_phases": "phases_and_towers",
    }
    data, states = dict(profile.profile_data or {}), dict(profile.field_states or {})
    changed = False
    for legacy, canonical in mapping.items():
        value = getattr(profile, legacy, None)
        if value not in (None, "", []) and canonical not in data:
            data[canonical] = value
            states[canonical] = {"status": "pending_confirmation", "applicable": True}
            changed = True
    if changed:
        profile.profile_data, profile.field_states = data, states


def apply_field_updates(
    db: Session, profile: ProjectProfile, updates: list[dict[str, Any]], *,
    allow_authoritative_statuses: bool, final_approved: bool | None = None,
) -> ApplyUpdatesResult:
    data, states, sources = dict(profile.profile_data or {}), dict(profile.field_states or {}), dict(profile.field_sources or {})
    accepted, rejected = [], []
    for raw in updates:
        update = dict(raw)
        key = normalize_field_key(update.get("field"))
        status = update.get("status", "extracted")
        if not key:
            rejected.append({"update": raw, "reason": "unknown_field"}); continue
        if status not in VALID_STATUSES:
            rejected.append({"update": raw, "reason": "invalid_status"}); continue
        if status in {"confirmed", "corrected_by_user", "not_applicable"} and not allow_authoritative_statuses:
            status = "pending_confirmation"
        value = update.get("value")
        if status not in {"missing", "not_applicable"} and value in (None, "", []):
            rejected.append({"update": raw, "reason": "missing_value"}); continue
        if status != "not_applicable" and value is not None:
            data[key] = value
        states[key] = {"status": status, "applicable": False if status == "not_applicable" else update.get("applicable", True)}
        source = {k: update.get(k) for k in ("source_type", "source_reference", "confidence") if update.get(k) is not None}
        if source:
            source["recorded_at"] = datetime.utcnow().isoformat(); sources[key] = source
        accepted.append({"field": key, "value": value, "status": status})
    if final_approved is not None and allow_authoritative_statuses:
        profile.final_approved = final_approved
    profile.profile_data, profile.field_states, profile.field_sources = data, states, sources
    for name in ("profile_data", "field_states", "field_sources"):
        flag_modified(profile, name)
    refresh_completion(profile)
    db.add(profile); db.commit(); db.refresh(profile)
    return ApplyUpdatesResult(accepted=accepted, rejected=rejected)


def refresh_completion(profile: ProjectProfile) -> dict[str, Any]:
    result = calculate_completion(profile.field_states, final_approved=profile.final_approved)
    profile.completion_percentage = result["percentage"]
    profile.is_fully_completed = result["can_complete"]
    profile.sales_activation_status = result["sales_activation_status"]
    if result["sales_activation_status"] == "ready" and profile.approved_for_sales_at is None:
        profile.approved_for_sales_at = datetime.utcnow()
    return result


def serialize_profile(profile: ProjectProfile) -> dict[str, Any]:
    return {
        "id": profile.id, "project_id": profile.project_id, "data": profile.profile_data or {},
        "fields": field_progress(profile.field_states), "completion": refresh_completion(profile),
        "updated_at": profile.updated_at,
    }


def serialize_project(project: Project) -> dict[str, Any]:
    return {
        "id": project.id, "company_id": project.company_id, "name": project.name,
        "description": project.description, "address": project.address, "city": project.city,
        "country": project.country, "is_active": project.is_active,
        "profile": serialize_profile(project.profile) if project.profile else None,
    }


def serialize_attachment(source: ProjectOnboardingSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "kind": source.kind.value,
        "name": source.name,
        "mime_type": source.mime_type,
        "size_bytes": source.size_bytes,
        "status": source.status.value,
        "url": source.url,
        "download_url": (
            f"/api/v1/projects/{source.project_id}/sources/{source.id}/file"
            if source.storage_path else None
        ),
    }


def serialize_message(message: ProjectMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "sender": "user" if message.sender == SenderType.USER else "ai",
        "content": message.content,
        "created_at": message.created_at,
        "attachments": [serialize_attachment(source) for source in message.attachments],
    }


def deletion_impact(db: Session, project: Project) -> dict[str, Any]:
    # Local imports avoid coupling the project model module to CRM and broker models.
    from app.modules.brokers.models import Broker
    from app.modules.sales_crm.models import Lead, Meeting

    leads = db.query(Lead).filter(Lead.project_id == project.id).count()
    meetings = db.query(Meeting).filter(Meeting.project_id == project.id).count()
    campaigns = db.query(ProjectCampaign).filter(ProjectCampaign.project_id == project.id).count()
    active_campaigns = db.query(ProjectCampaign).filter(
        ProjectCampaign.project_id == project.id,
        ProjectCampaign.status == "active",
    ).count()
    brokers = db.query(Broker).filter(Broker.project_id == project.id).count()
    sources = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id
    ).count()
    files = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).count()
    can_delete = leads == 0 and meetings == 0 and active_campaigns == 0
    return {
        "can_delete": can_delete,
        "leads": leads,
        "meetings": meetings,
        "campaigns": campaigns,
        "active_campaigns": active_campaigns,
        "brokers": brokers,
        "sources": sources,
        "files": files,
        "recommended_action": "delete" if can_delete else "archive",
    }


def archive_project(db: Session, project: Project) -> Project:
    project.is_active = False
    db.add(project); db.commit(); db.refresh(project)
    return project


def delete_project(db: Session, project: Project, *, confirm_name: str) -> None:
    if confirm_name.strip() != project.name:
        raise HTTPException(status_code=422, detail="Type the exact project name to confirm deletion.")
    impact = deletion_impact(db, project)
    if not impact["can_delete"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "This project has commercial activity and should be archived.", "impact": impact},
        )
    quarantined = storage_service.quarantine_project_files(project.company_id, project.id)
    try:
        db.delete(project)
        db.commit()
    except Exception:
        db.rollback()
        storage_service.restore_quarantined_files(quarantined)
        raise
    storage_service.purge_quarantined_files(quarantined)


def save_message(db: Session, session_id: str, sender: SenderType, content: str) -> ProjectMessage:
    message = ProjectMessage(session_id=session_id, sender=sender, content=content)
    db.add(message); db.commit(); db.refresh(message)
    return message
