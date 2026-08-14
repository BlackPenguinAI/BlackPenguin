from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.companies.models import Company
from app.modules.onboarding_questions import is_too_short, validate_onboarding_value

from .completion import FIELD_BY_KEY, VALID_STATUSES, calculate_completion, field_progress, normalize_field_key
from . import storage_service
from .models import (
    Project, ProjectCampaign, ProjectMessage, ProjectOnboardingProposal, ProjectOnboardingSource, ProjectProfile,
    ProjectProposalStatus, ProjectSourceKind, ProjectSourceStatus, ProjectUnit,
    ProjectSession, SenderType,
)


@dataclass
class ApplyUpdatesResult:
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


@dataclass
class QuestionResolution:
    handled: bool
    status: str
    updates: list[dict[str, Any]]
    reason: str | None = None
    question: ProjectMessage | None = None
    action: str | None = None


def check_project_limits(db: Session, company_id: str) -> None:
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.plan:
        raise HTTPException(status_code=400, detail="The company does not have an assigned plan.")
    current_count = db.query(Project).filter(
        Project.company_id == company_id,
        Project.is_active.is_(True),
        Project.is_demo.is_(False),
    ).count()
    if current_count >= company.plan.max_projects:
        raise HTTPException(status_code=400, detail=f"Your plan allows {company.plan.max_projects} projects.")


def get_project(db: Session, project_id: str, company_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def create_project_with_onboarding(db: Session, *, company_id: str, payload: dict[str, Any], draft: bool = False) -> Project:
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
    if draft:
        seed = {}
    profile.profile_data = {key: value for key, value in seed.items() if value not in (None, "")}
    profile.field_states = {
        key: {"status": "confirmed", "applicable": True}
        for key, value in seed.items() if value not in (None, "")
    }
    refresh_completion(profile)
    project.onboarding_status = "draft" if draft else "in_progress"
    db.commit()
    db.refresh(project)
    return project


def get_profile(project: Project) -> ProjectProfile:
    if not project.profile:
        raise HTTPException(status_code=500, detail="Project profile is missing.")
    seed_legacy_values(project.profile)
    return project.profile


def save_message(
    db: Session, session_id: str, sender: SenderType, content: str, *,
    ui_payload: dict[str, Any] | None = None,
    in_reply_to_message_id: str | None = None,
    message_id: str | None = None,
    commit: bool = True,
) -> ProjectMessage:
    if sender == SenderType.AI and isinstance(ui_payload, dict):
        supersede_unanswered_questions(db, session_id)
    message = ProjectMessage(
        id=message_id,
        session_id=session_id, sender=sender, content=content,
        ui_payload=ui_payload, in_reply_to_message_id=in_reply_to_message_id,
    )
    db.add(message)
    if commit:
        db.commit(); db.refresh(message)
    else:
        db.flush()
    return message


def supersede_unanswered_questions(
    db: Session,
    session_id: str,
    *,
    keep_message_id: str | None = None,
) -> bool:
    candidates = db.query(ProjectMessage).filter(
        ProjectMessage.session_id == session_id,
        ProjectMessage.sender == SenderType.AI,
        ProjectMessage.response_payload.is_(None),
    ).all()
    changed = False
    for message in candidates:
        if message.id == keep_message_id or not isinstance(message.ui_payload, dict):
            continue
        message.response_payload = {
            "status": "superseded",
            "answer": "",
            "selected_option": None,
            "custom": False,
        }
        db.add(message)
        changed = True
    return changed


def get_active_question(
    db: Session,
    session_id: str,
    requested_message_id: str | None = None,
) -> ProjectMessage | None:
    candidates = [
        message
        for message in db.query(ProjectMessage).filter(
            ProjectMessage.session_id == session_id,
            ProjectMessage.sender == SenderType.AI,
            ProjectMessage.response_payload.is_(None),
        ).order_by(ProjectMessage.created_at.desc(), ProjectMessage.id.desc()).all()
        if isinstance(message.ui_payload, dict)
    ]
    if not candidates:
        return None
    if requested_message_id == candidates[0].id:
        return candidates[0]
    return candidates[0]


def record_message_response(
    db: Session,
    session_id: str,
    message_id: str | None,
    answer: str,
    *,
    status: str = "accepted",
    commit: bool = True,
) -> None:
    if not message_id:
        return
    message = db.query(ProjectMessage).filter(
        ProjectMessage.id == message_id,
        ProjectMessage.session_id == session_id,
        ProjectMessage.sender == SenderType.AI,
    ).first()
    if not message or message.response_payload:
        return
    choices = ((message.ui_payload or {}).get("options") or (message.ui_payload or {}).get("examples") or [])
    selected = next((item for item in choices if str(item).casefold() == answer.strip().casefold()), None)
    message.response_payload = {
        "status": status, "answer": answer.strip(),
        "selected_option": selected, "custom": selected is None,
    }
    db.add(message)
    if commit:
        db.commit()
    else:
        db.flush()


def _user_update(
    field: str,
    value: Any,
    *,
    status: str = "confirmed",
    applicable: bool = True,
) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "status": status,
        "applicable": applicable,
        "source_type": "user",
        "source_reference": "project_onboarding_chat",
        "confidence": "high",
    }


def resolve_answer_to_question(
    db: Session,
    *,
    session_id: str,
    message_id: str | None,
    answer: str,
    profile: ProjectProfile,
) -> QuestionResolution:
    """Resolve a persisted structured question without depending on a model call."""
    if not message_id:
        return QuestionResolution(False, "not_applicable", [])
    question = db.query(ProjectMessage).filter(
        ProjectMessage.id == message_id,
        ProjectMessage.session_id == session_id,
        ProjectMessage.sender == SenderType.AI,
    ).first()
    if not question or not isinstance(question.ui_payload, dict):
        return QuestionResolution(True, "rejected", [], "invalid_question", question)
    if question.response_payload:
        return QuestionResolution(True, "rejected", [], "stale_question", question)

    active = get_active_question(db, session_id, message_id)
    if active and active.id != question.id:
        return QuestionResolution(True, "rejected", [], "stale_question", question)

    text = re.sub(r"\s+", " ", answer).strip()
    if not text:
        return QuestionResolution(True, "rejected", [], "empty_answer", question)

    answer_actions = question.ui_payload.get("answer_actions")
    action = None
    if isinstance(answer_actions, dict):
        action = next(
            (
                value
                for label, value in answer_actions.items()
                if str(label).strip().casefold() == text.casefold() and isinstance(value, dict)
            ),
            None,
        )
        if action and action.get("kind") in {"approve_profile", "request_changes"}:
            return QuestionResolution(
                True,
                "accepted",
                [],
                question=question,
                action=str(action["kind"]),
            )

    field = normalize_field_key(question.ui_payload.get("field"))
    if field is None:
        return QuestionResolution(False, "not_applicable", [], question=question)

    if action and action.get("kind") == "not_applicable":
        return QuestionResolution(
            True,
            "accepted",
            [_user_update(field, None, status="not_applicable", applicable=False)],
            question=question,
        )
    if action and action.get("kind") == "defer":
        return QuestionResolution(
            True,
            "accepted",
            [_user_update(field, None, status="deferred", applicable=True)],
            question=question,
        )

    definition = FIELD_BY_KEY[field]
    lowered = text.casefold()
    if definition.requirement == "conditionally_required" and lowered in {
        "none", "no", "not applicable", "n/a", "no aplica", "does not apply",
    }:
        return QuestionResolution(
            True,
            "accepted",
            [_user_update(field, None, status="not_applicable", applicable=False)],
            question=question,
        )

    input_type = str(question.ui_payload.get("input_type") or "text")
    value: Any
    if input_type == "multi_select":
        value = [item.strip() for item in re.split(r"[,;]", text) if item.strip()]
        if not value:
            return QuestionResolution(True, "rejected", [], "empty_answer", question)
    else:
        value = text

    validation_error = validate_onboarding_value(field, value)
    if validation_error:
        return QuestionResolution(
            True,
            "rejected",
            [],
            validation_error["code"],
            question,
        )
    existing = (profile.profile_data or {}).get(field)
    update_status = "corrected_by_user" if existing not in (None, "", []) and existing != value else "confirmed"
    return QuestionResolution(
        True,
        "accepted",
        [_user_update(field, value, status=update_status)],
        question=question,
    )


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
    commit: bool = True,
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
        if status not in {"missing", "not_applicable", "deferred"} and value in (None, "", []):
            rejected.append({"update": raw, "reason": "missing_value"}); continue
        if is_too_short(key, value):
            rejected.append({"update": raw, "reason": "answer_too_short"}); continue
        if status not in {"not_applicable", "deferred"} and value is not None:
            data[key] = value
        states[key] = {"status": status, "applicable": False if status == "not_applicable" else update.get("applicable", True)}
        source = {k: update.get(k) for k in ("source_type", "source_reference", "confidence") if update.get(k) is not None}
        if source:
            source["recorded_at"] = datetime.utcnow().isoformat(); sources[key] = source
        accepted.append({"field": key, "value": value, "status": status})
        if key == "project_name" and value and status in {"confirmed", "corrected_by_user"}:
            profile.project.name = str(value)[:150]
        elif key == "short_description" and value:
            profile.project.description = str(value)
        elif key == "exact_address" and value:
            profile.project.address = str(value)[:255]
        elif key == "city" and value:
            profile.project.city = str(value)[:100]
        elif key == "country" and value:
            profile.project.country = str(value)[:100]
    if accepted and profile.project.onboarding_status == "completed":
        profile.final_approved = False
        profile.approved_for_sales_at = None
        profile.project.onboarding_status = "awaiting_confirmation"
        profile.project.onboarding_completed_at = None
        profile.project.onboarding_approved_by_user_id = None
    elif accepted and profile.project.onboarding_status == "draft":
        profile.project.onboarding_status = "in_progress"
    profile.profile_data, profile.field_states, profile.field_sources = data, states, sources
    for name in ("profile_data", "field_states", "field_sources"):
        flag_modified(profile, name)
    refresh_completion(profile)
    db.add(profile)
    if commit:
        db.commit(); db.refresh(profile)
    else:
        db.flush()
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
    completion = refresh_completion(profile)
    completion["ready_for_confirmation"] = (
        completion["required_fields_complete"] and not profile.final_approved
        and profile.project.onboarding_status in {"in_progress", "awaiting_confirmation"}
    )
    return {
        "id": profile.id, "project_id": profile.project_id, "data": profile.profile_data or {},
        "fields": field_progress(profile.field_states), "completion": completion,
        "updated_at": profile.updated_at,
    }


def serialize_project(project: Project) -> dict[str, Any]:
    serialized_profile = serialize_profile(project.profile) if project.profile else None
    if project.is_demo and serialized_profile:
        serialized_profile["completion"]["sales_activation_status"] = "demo_only"
    return {
        "id": project.id, "company_id": project.company_id, "name": project.name,
        "description": project.description, "address": project.address, "city": project.city,
        "country": project.country, "is_active": project.is_active,
        "is_demo": project.is_demo,
        "demo_template_version": project.demo_template_version,
        "onboarding_status": project.onboarding_status,
        "profile": serialized_profile,
    }


def readiness_for_confirmation(db: Session, project: Project) -> tuple[bool, list[str]]:
    completion = refresh_completion(get_profile(project))
    reasons: list[str] = []
    if not completion["required_fields_complete"]:
        reasons.append("required_fields")
    if db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.status == ProjectSourceStatus.PROCESSING,
    ).first():
        reasons.append("processing_sources")
    if db.query(ProjectOnboardingProposal).join(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingProposal.status == ProjectProposalStatus.PENDING,
    ).first():
        reasons.append("pending_proposals")
    return not reasons, reasons


def complete_onboarding(db: Session, project: Project, user_id: str) -> ProjectProfile:
    profile = get_profile(project)
    ready, reasons = readiness_for_confirmation(db, project)
    if project.onboarding_status == "completed" and profile.final_approved:
        return profile
    if not ready:
        raise HTTPException(status_code=409, detail={
            "message": "The Project Profile is not ready for final confirmation.",
            "blockers": reasons,
        })
    now = datetime.utcnow()
    profile.final_approved = True
    profile.approved_for_sales_at = now
    project.onboarding_status = "completed"
    project.onboarding_completed_at = now
    project.onboarding_approved_by_user_id = user_id
    refresh_completion(profile)
    db.add_all([profile, project]); db.commit(); db.refresh(profile)
    return profile


def serialize_overview(db: Session, project: Project) -> dict[str, Any]:
    profile = get_profile(project)
    data = profile.profile_data or {}
    units = db.query(ProjectUnit).filter(ProjectUnit.project_id == project.id).all()
    cover = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project.id,
        ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE,
        ProjectOnboardingSource.status == ProjectSourceStatus.READY,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).order_by(ProjectOnboardingSource.is_primary.desc(), ProjectOnboardingSource.created_at.asc()).first()
    inventory: list[dict[str, Any]] = []
    if units:
        typologies = sorted({unit.typology or "Unclassified" for unit in units})
        for typology in typologies:
            group = [unit for unit in units if (unit.typology or "Unclassified") == typology]
            available = [unit for unit in group if unit.status == "available"]
            sold = [unit for unit in group if unit.status == "sold"]
            prices = [float(unit.list_price) for unit in group if unit.list_price is not None]
            inventory.append({
                "typology": typology, "total": len(group), "sold": len(sold), "available": len(available),
                "starting_price": min(prices) if prices else None,
                "currency": next((unit.currency for unit in group if unit.currency), data.get("currency")),
            })
    else:
        raw_typologies = data.get("typologies") or []
        if isinstance(raw_typologies, str):
            raw_typologies = [item.strip() for item in raw_typologies.split(",") if item.strip()]
        inventory = [{"typology": str(item), "total": None, "sold": None, "available": None,
                      "starting_price": None, "currency": data.get("currency")} for item in raw_typologies]

    available_count = sum(1 for unit in units if unit.status == "available") if units else None
    revenue = sum(float(unit.list_price) for unit in units if unit.status == "sold" and unit.list_price is not None) if units else None
    currency = data.get("currency")
    starting_price = data.get("starting_price")
    metrics = [
        {"key": "available_inventory", "label": "Available Inventory", "value": available_count,
         "display_value": str(available_count) if available_count is not None else str(data.get("available_inventory") or "Pending"),
         "status": "available" if available_count is not None or data.get("available_inventory") else "pending"},
        {"key": "starting_price", "label": "Starting Price", "value": starting_price,
         "display_value": f"{currency or ''} {starting_price}".strip() if starting_price else "Pending",
         "status": "available" if starting_price else "pending"},
        {"key": "target_roi", "label": "Target ROI (Return on Investment)", "value": None, "display_value": "Pending", "status": "pending"},
    ]
    address_parts = [data.get("exact_address") or project.address, data.get("city") or project.city, data.get("country") or project.country]
    address = ", ".join(str(part) for part in address_parts if part)
    return {
        "id": project.id, "name": data.get("project_name") or project.name,
        "status": data.get("project_status"), "description": data.get("short_description") or project.description,
        "address": data.get("exact_address") or project.address, "city": data.get("city") or project.city,
        "country": data.get("country") or project.country, "delivery_dates": data.get("delivery_dates"),
        "cover_image_url": f"/api/v1/projects/{project.id}/sources/{cover.id}/file" if cover else None,
        "cover_focal_point": {"x": cover.focal_point_x, "y": cover.focal_point_y} if cover else {"x": .5, "y": .5},
        "metrics": metrics, "inventory": inventory,
        "location": {"address": address or None, "latitude": project.latitude, "longitude": project.longitude},
        "market_intelligence": {"report_url": f"/app/projects/{project.id}/sales-report", "total_revenue": revenue,
                                "target_roi": None, "status": "available" if units else "pending"},
        "data_completeness": {"percentage": profile.completion_percentage, "onboarding_status": project.onboarding_status,
                              "last_updated_at": profile.updated_at},
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
        "ui_payload": message.ui_payload,
        "response_payload": message.response_payload,
        "in_reply_to_message_id": message.in_reply_to_message_id,
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
    if project.is_demo:
        raise HTTPException(status_code=409, detail="The Demo Project cannot be archived. Reset it instead.")
    project.is_active = False
    db.add(project); db.commit(); db.refresh(project)
    return project


def delete_project(db: Session, project: Project, *, confirm_name: str) -> None:
    if project.is_demo:
        raise HTTPException(status_code=409, detail="The Demo Project cannot be deleted. Reset it instead.")
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
