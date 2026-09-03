from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
import httpx
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.onboarding_questions import build_next_question
from app.modules.onboarding_jobs import service as job_service
from app.modules.onboarding_jobs.continuation import finalize_source_group
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_copy import conversational_acknowledgement
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users.project_access import project_ids_for_user, require_project_access

from . import asset_share_service, catalog_service, meta_service, services, source_service, storage_service
from .completion import FIELD_BY_KEY
from .models import (
    MetaConnection, Project, ProjectCampaign, ProjectMessage, ProjectOnboardingProposal,
    ProjectOnboardingSource, ProjectPropertyType, ProjectSession, ProjectSourceKind, ProjectSourceStatus, SenderType,
)
from .schemas import (
    CampaignCreate, CampaignResponse, ChatBootstrapRequest, ChatMessagePayload, ChatMessageResponse, ChatTurnResponse,
    MetaConnectionCreate, MetaConnectionResponse, MetaProjectSetupRequest, MetaProjectSetupResponse,
    MetaSetupConfigurationResponse, ProjectCreate, ProjectProfilePatch, ProjectTimezoneUpdate,
    ProjectOnboardingActionRequest,
    ProjectCompleteResponse, ProjectDeleteRequest, ProjectDeletionImpact, ProjectDraftResponse,
    ProjectOverviewResponse, ProjectProfileResponse, ProjectResponse,
    PropertyTypeCatalogResponse, PropertyTypeCreate, PropertyTypeMediaAttach,
    PropertyTypeResponse, PropertyTypeUpdate, ProjectMarketingSummary,
    OnboardingStateResponse, ProposalDecision, ProposalDecisionResponse,
    SourceResponse, UrlSourceRequest,
)
from app.modules.demo_projects.service import provision_demo_project


router = APIRouter()
EDITOR_ROLES = [*TENANT_MANAGER_ROLES, UserRole.MKT]
VIEWER_ROLES = [*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES]
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


@router.get("/shared-assets/{token}", include_in_schema=False)
def download_shared_sales_asset(token: str, db: Session = Depends(get_db)):
    source = asset_share_service.resolve(db, token)
    try:
        path = storage_service.resolve_project_file(source.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Shared image not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Shared image not found.")
    return FileResponse(path, media_type=source.mime_type or "application/octet-stream", filename=source.original_filename or source.name,
                        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


def _parse_agent_response(raw: str) -> tuple[str, list[dict[str, Any]], bool | None] | None:
    try:
        payload = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("assistant_message"), str):
        return None
    updates = payload.get("verified_updates", [])
    if not isinstance(updates, list) or any(not isinstance(item, dict) for item in updates):
        return None
    approved = payload.get("final_approved")
    return payload["assistant_message"].strip(), updates, approved if isinstance(approved, bool) else None


def _message(message: ProjectMessage) -> dict[str, Any]:
    return services.serialize_message(message)


def _turn_payload(
    *,
    request_id: str,
    ai_message: ProjectMessage,
    user_message: ProjectMessage,
    profile,
    accepted: list[dict[str, Any]] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    assistant_status: str = "deterministic",
    sources: list[ProjectOnboardingSource] | None = None,
) -> dict[str, Any]:
    accepted = accepted or []
    rejected = rejected or []
    return {
        "request_id": request_id,
        "message_saved": True,
        "profile_changed": bool(accepted),
        "field_update_status": "accepted" if accepted else ("rejected" if rejected else "not_applicable"),
        "assistant_status": assistant_status,
        "message": _message(ai_message),
        "user_message": _message(user_message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [item["field"] for item in accepted],
        "rejected_updates": [
            {"field": item.get("update", {}).get("field"), "reason": item["reason"]}
            for item in rejected
        ],
        "sources": [source_service.serialize_source(source) for source in (sources or [])],
        "next_question": _next_question(profile),
    }


def _existing_turn(
    db: Session,
    *,
    project: Project,
    client_message_id: str | None,
    request_id: str,
) -> dict[str, Any] | None:
    if not client_message_id:
        return None
    user_message = db.query(ProjectMessage).filter(ProjectMessage.id == client_message_id).first()
    if not user_message:
        return None
    if user_message.session_id != project.session.id or user_message.sender != SenderType.USER:
        raise HTTPException(status_code=409, detail="That message identifier is already in use.")
    ai_message = db.query(ProjectMessage).filter(
        ProjectMessage.session_id == project.session.id,
        ProjectMessage.sender == SenderType.AI,
        ProjectMessage.in_reply_to_message_id == user_message.id,
    ).order_by(ProjectMessage.created_at.desc()).first()
    recovered_interrupted_turn = ai_message is None
    if not ai_message:
        profile = services.get_profile(project)
        ai_message = services.save_message(
            db,
            project.session.id,
            SenderType.AI,
            "Your previous message was saved, but its assistant response was interrupted. "
            + _next_prompt(profile),
            ui_payload=_next_question(profile),
            in_reply_to_message_id=user_message.id,
        )
    sources = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.message_id == user_message.id,
    ).all()
    return _turn_payload(
        request_id=request_id,
        ai_message=ai_message,
        user_message=user_message,
        profile=services.get_profile(project),
        assistant_status="fallback" if recovered_interrupted_turn else "deterministic",
        sources=sources,
    )


def _next_prompt(profile) -> str:
    return _next_question(profile)["prompt"]


def _next_question(profile) -> dict[str, Any]:
    blockers = services.serialize_profile(profile)["completion"]["blockers"]
    catalog_managed_fields = {
        "typologies", "available_inventory", "starting_price", "currency", "inventory_updated_at",
    }
    if blockers and blockers[0]["field"] in catalog_managed_fields:
        blockers = [{
            "field": "property_type_catalog",
            "label": "Confirmed property type catalog",
            "section": "product",
            "status": "missing",
            "requirement": "required",
        }, *blockers[1:]]
    return build_next_question(
        blockers,
        final_prompt="Review the Project Profile and choose whether to approve it or make changes.",
        profile_data=profile.profile_data or {},
    )


def _continue_after_source_review(
    db: Session,
    *,
    proposal: ProjectOnboardingProposal,
    profile,
) -> ProjectMessage | None:
    return finalize_source_group(
        db,
        scope="project",
        company_id=proposal.source.project.company_id,
        project_id=proposal.source.project_id,
        message_id=proposal.source.message_id,
    )


def _state_payload(db: Session, project: Project) -> dict[str, Any]:
    profile = services.get_profile(project)
    messages = (
        db.query(ProjectMessage)
        .options(joinedload(ProjectMessage.attachments))
        .filter(ProjectMessage.session_id == project.session.id)
        .order_by(ProjectMessage.created_at.asc())
        .all()
    )
    sources = (
        db.query(ProjectOnboardingSource)
        .filter(ProjectOnboardingSource.project_id == project.id)
        .order_by(ProjectOnboardingSource.created_at.desc())
        .all()
    )
    serialized_profile = services.serialize_profile(profile)
    ready_for_confirmation, _ = services.readiness_for_confirmation(db, project)
    serialized_profile["completion"]["ready_for_confirmation"] = ready_for_confirmation and not profile.final_approved
    processing = any(source.status.value == "processing" for source in sources) or db.query(OnboardingSourceJob).filter(
        OnboardingSourceJob.scope == "project",
        OnboardingSourceJob.project_id == project.id,
        OnboardingSourceJob.company_id == project.company_id,
        OnboardingSourceJob.status.in_(["queued", "processing"]),
    ).first() is not None
    pending_review = any(
        proposal.status.value == "pending"
        for source in sources
        for proposal in source.proposals
    )
    if not processing and not pending_review:
        latest_ai = next((item for item in reversed(messages) if item.sender == SenderType.AI), None)
        desired_question = _next_question(profile)
        if latest_ai and not latest_ai.response_payload and (
            not latest_ai.ui_payload
            or (latest_ai.ui_payload or {}).get("field") != desired_question.get("field")
        ):
            services.supersede_unanswered_questions(
                db,
                project.session.id,
                keep_message_id=latest_ai.id,
            )
            latest_ai.ui_payload = desired_question
            latest_ai.content = desired_question["prompt"]
            db.add(latest_ai); db.commit(); db.refresh(latest_ai)
    if serialized_profile["completion"]["can_complete"]:
        stage = "complete"
    elif processing:
        stage = "processing"
    elif pending_review:
        stage = "review"
    elif ready_for_confirmation:
        stage = "awaiting_confirmation"
        if project.onboarding_status != "awaiting_confirmation":
            project.onboarding_status = "awaiting_confirmation"
            db.add(project); db.commit()
    elif not messages and not sources:
        stage = "website"
    else:
        stage = "conversation"
    timestamps = [profile.updated_at, *[item.created_at for item in messages], *[item.updated_at for item in sources]]
    version = int(max((item.timestamp() for item in timestamps if item), default=0) * 1000)
    return {
        "messages": [_message(message) for message in messages],
        "profile": serialized_profile,
        "sources": [source_service.serialize_source(source) for source in sources],
        "next_question": _next_question(profile),
        "stage": stage,
        "version": version,
    }


def _system_instruction(config: dict[str, Any]) -> str:
    catalog = [{"key": key, "label": field.label, "section": field.section} for key, field in FIELD_BY_KEY.items()]
    return (
        f"{config.get('system_prompt', '')}\n\nFLOW PROTOCOL:\n{config.get('protocol_prompt', '')}"
        f"\n\nGUARDRAILS:\n{config.get('guardrails_prompt', '')}\n\n"
        "Return only one JSON object with assistant_message, verified_updates, and final_approved. "
        "Always set final_approved to false; only the application's explicit confirmation action can finish onboarding. "
        "verified_updates items use field, value, status, applicable, source_type, source_reference, confidence. "
        "Use only canonical keys from this catalog. Do not say data was saved; the application validates writes. "
        f"FIELD CATALOG: {json.dumps(catalog)}"
    )


async def _complete_chat_turn(
    *, db: Session, project: Project, current_user: User, user_message: ProjectMessage,
    sources: list[ProjectOnboardingSource], source_errors: list[dict[str, Any]],
    request_id: str,
) -> dict[str, Any]:
    profile = services.get_profile(project)
    if any(source.status.value == "processing" for source in sources):
        processing_names = ", ".join(f"**{source.name}**" for source in sources if source.status.value == "processing")
        db.query(ProjectSession).filter(
            ProjectSession.id == project.session.id,
        ).with_for_update().one()
        ai_message = db.query(ProjectMessage).filter(
            ProjectMessage.session_id == project.session.id,
            ProjectMessage.sender == SenderType.AI,
            ProjectMessage.in_reply_to_message_id == user_message.id,
        ).order_by(ProjectMessage.created_at.desc()).first()
        if not ai_message:
            ai_message = services.save_message(
                db,
                project.session.id,
                SenderType.AI,
                f"I'm processing {processing_names}. The result will appear automatically, and the onboarding will continue when every source in this message has finished.",
                in_reply_to_message_id=user_message.id,
            )
        db.refresh(user_message)
        return {
            "request_id": request_id,
            "message_saved": True,
            "profile_changed": False,
            "field_update_status": "not_applicable",
            "assistant_status": "deterministic",
            "message": _message(ai_message),
            "user_message": _message(user_message),
            "profile": services.serialize_profile(profile),
            "accepted_fields": [],
            "rejected_updates": [],
            "sources": [source_service.serialize_source(source) for source in sources],
            "next_question": _next_question(profile),
        }
    ai_config = get_ai_config(db, current_user.company_id)
    history = db.query(ProjectMessage).filter(
        ProjectMessage.session_id == project.session.id
    ).order_by(ProjectMessage.created_at.asc()).all()
    company_profile = db.query(CompanyProfile).filter(
        CompanyProfile.company_id == current_user.company_id
    ).first()
    campaigns = db.query(ProjectCampaign).filter(ProjectCampaign.project_id == project.id).all()
    config = ai_config.agent_onboarding_proyectos or {}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_instruction(config)},
        {"role": "system", "content": "RUNTIME CONTEXT:\n" + json.dumps({
            "current_user": {"first_name": current_user.first_name, "role": current_user.role.value},
            "company_profile": company_profile.profile_data if company_profile else {},
            "project": {"id": project.id, "name": project.name},
            "profile": services.serialize_profile(profile),
            "campaigns": [{"name": c.name, "platform": c.platform, "status": c.status} for c in campaigns],
            "new_sources": [source_service.serialize_source(source) for source in sources],
            "source_errors": source_errors,
        }, ensure_ascii=False, default=str)},
    ]
    for item in history[-12:]:
        messages.append({"role": "user" if item.sender == SenderType.USER else "assistant", "content": item.content})
    model = config.get("model", "openai/gpt-4o-mini")
    assistant_status = "llm"
    try:
        if not ai_config.openrouter_api_key:
            raise ValueError("AI configuration is incomplete")
        raw = await generate_llm_response(
            ai_config.openrouter_api_key, model, messages,
            response_format={"type": "json_object"}, temperature=0.25, raise_on_error=True,
            timeout_seconds=20.0,
        )
        parsed = _parse_agent_response(raw)
    except (httpx.HTTPError, ValueError) as exc:
        parsed = None
        assistant_status = "fallback"

    if parsed is None:
        assistant_text, updates, approved = (
            "I saved your message, but the assistant is temporarily unavailable. " + _next_prompt(profile),
            [],
            None,
        )
        assistant_status = "fallback"
    else:
        assistant_text, updates, approved = parsed
    result = services.apply_field_updates(
        db, profile, updates, allow_authoritative_statuses=current_user.role in EDITOR_ROLES,
        final_approved=None,
    )
    if result.accepted:
        assistant_text = conversational_acknowledgement(
            accepted=result.accepted,
            label_for=lambda field: FIELD_BY_KEY[field].label,
            next_prompt=_next_prompt(profile),
            first_name=current_user.first_name,
            scope="Project Profile",
        )
    elif result.rejected:
        assistant_text = "I couldn't safely apply that information, so nothing was changed. " + _next_prompt(profile)
    db.query(ProjectSession).filter(ProjectSession.id == project.session.id).with_for_update().one()
    ai_message = db.query(ProjectMessage).filter(
        ProjectMessage.session_id == project.session.id,
        ProjectMessage.sender == SenderType.AI,
        ProjectMessage.in_reply_to_message_id == user_message.id,
    ).order_by(ProjectMessage.created_at.desc()).first()
    if not ai_message:
        ai_message = services.save_message(
            db, project.session.id, SenderType.AI, assistant_text,
            ui_payload=_next_question(profile),
            in_reply_to_message_id=user_message.id,
        )
    db.refresh(user_message)
    return {
        "request_id": request_id,
        "message_saved": True,
        "profile_changed": bool(result.accepted),
        "field_update_status": "accepted" if result.accepted else ("rejected" if result.rejected else "not_applicable"),
        "assistant_status": assistant_status,
        "message": _message(ai_message),
        "user_message": _message(user_message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [item["field"] for item in result.accepted],
        "rejected_updates": [
            {"field": item.get("update", {}).get("field"), "reason": item["reason"]}
            for item in result.rejected
        ],
        "sources": [source_service.serialize_source(source) for source in sources],
        "next_question": _next_question(profile),
    }


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    services.check_project_limits(db, current_user.company_id)
    try:
        project = services.create_project_with_onboarding(
            db, company_id=current_user.company_id, payload=payload.model_dump()
        )
    except Exception:
        db.rollback(); raise
    return services.serialize_project(project)


@router.post("/drafts", response_model=ProjectDraftResponse, status_code=status.HTTP_201_CREATED)
def create_project_draft(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    services.check_project_limits(db, current_user.company_id)
    try:
        project = services.create_project_with_onboarding(
            db, company_id=current_user.company_id, payload={"name": "Untitled Project"}, draft=True,
        )
    except Exception:
        db.rollback(); raise
    return {"id": project.id, "onboarding_url": f"/app/projects/{project.id}/onboarding", "onboarding_status": project.onboarding_status}


@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    projects = db.query(Project).options(joinedload(Project.profile)).filter(
        Project.company_id == current_user.company_id,
        Project.is_active.is_(True),
    )
    allowed = project_ids_for_user(db, current_user)
    projects = (projects.filter(Project.id.in_(allowed)) if allowed else projects.filter(Project.id == "")).order_by(Project.created_at.desc()).all()
    return [services.serialize_project(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    require_project_access(db, current_user, project_id)
    return services.serialize_project(services.get_project(db, project_id, current_user.company_id))


@router.patch("/{project_id}/timezone", response_model=ProjectResponse)
def update_project_timezone(
    project_id: str,
    payload: ProjectTimezoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Unknown timezone.") from exc
    project = services.get_project(db, project_id, current_user.company_id)
    project.timezone = payload.timezone
    db.add(project); db.commit(); db.refresh(project)
    return services.serialize_project(project)


@router.get("/{project_id}/overview", response_model=ProjectOverviewResponse)
def get_project_overview(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(VIEWER_ROLES)),
):
    require_project_access(db, current_user, project_id)
    project = services.get_project(db, project_id, current_user.company_id)
    return services.serialize_overview(db, project)


@router.post("/{project_id}/onboarding/complete", response_model=ProjectCompleteResponse)
def complete_project_onboarding(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    profile = services.complete_onboarding(db, project, current_user.id)
    return {"completed": True, "redirect_url": f"/app/projects/{project.id}", "profile": services.serialize_profile(profile)}


@router.post("/{project_id}/sources/{source_id}/cover", response_model=SourceResponse)
def set_project_cover(
    project_id: str, source_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    services.get_project(db, project_id, current_user.company_id)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == source_id,
        ProjectOnboardingSource.project_id == project_id,
        ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Project image not found.")
    db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.project_id == project_id,
        ProjectOnboardingSource.kind == ProjectSourceKind.IMAGE,
    ).update({ProjectOnboardingSource.is_primary: False}, synchronize_session=False)
    source.is_primary = True
    profile = services.get_profile(source.project)
    active_question = services.get_active_question(db, source.project.session.id)
    updates = [services.user_field_update("project_cover", source.id)]
    services.apply_field_updates(db, profile, updates, allow_authoritative_statuses=True, commit=False)
    if active_question and (active_question.ui_payload or {}).get("input_type") == "project_cover":
        services.record_message_response(
            db, source.project.session.id, active_question.id,
            f"Confirmed Project cover: {source.name}", commit=False,
        )
        services.save_message(
            db, source.project.session.id, SenderType.AI, _next_prompt(profile),
            ui_payload=_next_question(profile), in_reply_to_message_id=active_question.id,
            commit=False,
        )
    db.add(source); db.commit(); db.refresh(source)
    return source_service.serialize_source(source)


@router.post("/{project_id}/sources/cover-upload", response_model=SourceResponse, status_code=201)
async def upload_project_cover_candidate(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    source = await source_service.create_file_source(
        db, project_id=project.id, company_id=current_user.company_id,
        user_id=current_user.id, upload=file, message_id=None,
    )
    if source.kind != ProjectSourceKind.IMAGE or not source.storage_path:
        if source.status != ProjectSourceStatus.FAILED:
            source.status = ProjectSourceStatus.FAILED
            source.error_message = "Use a valid JPG, PNG, or WEBP image."
            db.add(source); db.commit()
        raise HTTPException(status_code=422, detail=source.error_message or "Use a valid JPG, PNG, or WEBP image.")
    source.status = ProjectSourceStatus.READY
    source.extracted_text = "[User-uploaded Project cover candidate]"
    source.error_message = None
    db.add(source); db.commit(); db.refresh(source)
    return source_service.serialize_source(source)


def _property_type(db: Session, project_id: str, property_type_id: str) -> ProjectPropertyType:
    item = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.id == property_type_id,
        ProjectPropertyType.project_id == project_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Property type not found.")
    return item


@router.get("/{project_id}/property-types", response_model=PropertyTypeCatalogResponse)
def list_property_types(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(VIEWER_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return catalog_service.catalog(db, project)


@router.post("/{project_id}/property-types/confirm", response_model=PropertyTypeCatalogResponse)
def confirm_property_type_catalog(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    active_question = services.get_active_question(db, project.session.id)
    result = catalog_service.confirm_catalog(db, project)
    profile = services.get_profile(project)
    if active_question and (active_question.ui_payload or {}).get("input_type") == "property_type_catalog":
        services.record_message_response(
            db, project.session.id, active_question.id,
            "Confirmed the current property type catalog", commit=False,
        )
        services.save_message(
            db, project.session.id, SenderType.AI, _next_prompt(profile),
            ui_payload=_next_question(profile), in_reply_to_message_id=active_question.id,
            commit=False,
        )
        db.commit()
    return result


@router.post("/{project_id}/property-types", response_model=PropertyTypeResponse, status_code=201)
def create_property_type(
    project_id: str, payload: PropertyTypeCreate, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    try:
        return catalog_service.serialize(catalog_service.create(db, project, payload.model_dump(), user_id=current_user.id))
    except Exception:
        db.rollback()
        raise


@router.put("/{project_id}/property-types/{property_type_id}", response_model=PropertyTypeResponse)
def update_property_type(
    project_id: str, property_type_id: str, payload: PropertyTypeUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    item = _property_type(db, project.id, property_type_id)
    try:
        return catalog_service.serialize(catalog_service.update(db, project, item, payload.model_dump(), user_id=current_user.id))
    except Exception:
        db.rollback()
        raise


@router.delete("/{project_id}/property-types/{property_type_id}", status_code=204)
def delete_property_type(
    project_id: str, property_type_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    item = _property_type(db, project.id, property_type_id)
    db.delete(item); db.flush(); catalog_service._sync_profile(db, project); db.commit()
    return Response(status_code=204)


@router.post("/{project_id}/property-types/{property_type_id}/media", response_model=PropertyTypeResponse)
def attach_property_type_media(
    project_id: str, property_type_id: str, payload: PropertyTypeMediaAttach,
    db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    item = _property_type(db, project.id, property_type_id)
    return catalog_service.serialize(catalog_service.attach_media(db, project, item, payload.source_ids))


@router.post("/{project_id}/property-types/{property_type_id}/defer-images", response_model=PropertyTypeResponse)
def defer_property_type_images(
    project_id: str, property_type_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    item = _property_type(db, project.id, property_type_id)
    item.images_status = "deferred"; db.add(item); db.commit(); db.refresh(item)
    return catalog_service.serialize(item)


@router.get("/{project_id}/deletion-impact", response_model=ProjectDeletionImpact)
def get_deletion_impact(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return services.deletion_impact(db, project)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
def archive_project(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return services.serialize_project(services.archive_project(db, project))


@router.post("/{project_id}/demo/reset", response_model=ProjectResponse)
def reset_demo_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    if not project.is_demo:
        raise HTTPException(status_code=409, detail="Only the Demo Project can be reset.")
    if project.demo_template_version != "v1":
        raise HTTPException(
            status_code=409,
            detail="This versioned Demo Project is refreshed by its dedicated seed command.",
        )
    try:
        project = provision_demo_project(
            db,
            company_id=current_user.company_id,
            approved_by_user_id=current_user.id,
            template_version=project.demo_template_version,
        )
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        raise
    return services.serialize_project(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str, payload: ProjectDeleteRequest, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    services.delete_project(db, project, confirm_name=payload.confirm_name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/profile", response_model=ProjectProfileResponse)
def get_profile(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    return services.serialize_profile(services.get_profile(services.get_project(db, project_id, current_user.company_id)))


@router.patch("/{project_id}/profile", response_model=ProjectProfileResponse)
def patch_profile(project_id: str, payload: ProjectProfilePatch, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    profile = services.get_profile(services.get_project(db, project_id, current_user.company_id))
    services.apply_field_updates(db, profile, [item.model_dump() for item in payload.updates], allow_authoritative_statuses=True, final_approved=payload.final_approved)
    return services.serialize_profile(profile)


@router.get("/{project_id}/chat", response_model=list[ChatMessageResponse])
def get_chat(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    messages = db.query(ProjectMessage).options(
        joinedload(ProjectMessage.attachments)
    ).filter(ProjectMessage.session_id == project.session.id).order_by(ProjectMessage.created_at.asc()).all()
    return [services.serialize_message(item) for item in messages]


@router.get("/{project_id}/chat/state", response_model=OnboardingStateResponse)
def get_chat_state(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return _state_payload(db, project)


@router.post("/{project_id}/onboarding/actions", response_model=ChatTurnResponse)
def apply_onboarding_action(
    project_id: str,
    payload: ProjectOnboardingActionRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    """Resolve UI-owned onboarding steps without routing internal commands through the LLM chat."""
    request_id = f"req_{uuid.uuid4().hex}"
    response.headers["X-Request-ID"] = request_id
    project = services.get_project(db, project_id, current_user.company_id)
    db.query(ProjectSession).filter(ProjectSession.id == project.session.id).with_for_update().one()
    existing = _existing_turn(
        db,
        project=project,
        client_message_id=payload.client_action_id,
        request_id=request_id,
    )
    if existing:
        return existing

    question = services.get_active_question(
        db,
        project.session.id,
        payload.question_message_id,
    )
    if not question or question.id != payload.question_message_id:
        raise HTTPException(status_code=409, detail="That onboarding step is no longer active. Refresh and continue from the current step.")
    input_type = str((question.ui_payload or {}).get("input_type") or "")
    expected_input = {
        "authorize_ai_sales": "ai_sales_authorization",
        "complete_sales_team": "project_sales_team",
        "defer_sales_team": "project_sales_team",
        "complete_meta_setup": "meta_lead_setup",
        "defer_meta_setup": "meta_lead_setup",
    }[payload.action]
    if input_type != expected_input:
        raise HTTPException(status_code=409, detail="That action does not match the current onboarding step.")
    if payload.action == "authorize_ai_sales" and current_user.role not in TENANT_MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only a Company administrator or assistant can authorize AI-assisted sales.")

    content_by_action = {
        "authorize_ai_sales": "Authorize AI-assisted sales and continue",
        "complete_sales_team": "Continue with the assigned Sales team",
        "defer_sales_team": "Configure the Sales team later",
        "complete_meta_setup": "Run the simulated Meta connection test",
        "defer_meta_setup": "Configure Meta Lead Ads later",
    }
    user_message = services.save_message(
        db,
        project.session.id,
        SenderType.USER,
        content_by_action[payload.action],
        in_reply_to_message_id=question.id,
        message_id=payload.client_action_id,
        commit=False,
    )
    profile = services.get_profile(project)
    updates: list[dict[str, Any]] = []
    try:
        if payload.action == "authorize_ai_sales":
            updates = [services.user_field_update("sales_authorization", True)]
        elif payload.action == "complete_sales_team":
            assignments = (
                db.query(ProjectUserAssignment)
                .join(User, User.id == ProjectUserAssignment.user_id)
                .filter(
                    ProjectUserAssignment.project_id == project.id,
                    ProjectUserAssignment.responsibility == "sales",
                    ProjectUserAssignment.is_active.is_(True),
                    ProjectUserAssignment.accepts_new_leads.is_(True),
                    User.is_active.is_(True),
                    User.role == UserRole.SALES,
                )
                .all()
            )
            if not assignments:
                raise HTTPException(status_code=422, detail="Assign at least one active Sales user before continuing.")
            updates = [
                services.user_field_update("sales_contacts", [item.user_id for item in assignments]),
                services.user_field_update("appointment_routing", "round_robin"),
            ]
        elif payload.action == "defer_sales_team":
            updates = [
                services.user_field_update("sales_contacts", None, status="deferred"),
                services.user_field_update("appointment_routing", "round_robin", status="deferred"),
            ]
        elif payload.action == "complete_meta_setup":
            partner_id = settings.META_BUSINESS_MANAGER_ID.strip() or None
            if not partner_id:
                raise HTTPException(status_code=503, detail="Black Penguin's Meta Business Manager ID is not configured yet.")
            required_ids = (payload.page_id, payload.ad_account_id, payload.lead_form_id)
            if any(value is None for value in required_ids):
                raise HTTPException(status_code=422, detail="Page ID, Ad Account ID, and Form ID are required.")
            connection, _ = meta_service.simulate_project_setup(
                db,
                project=project,
                page_id=payload.page_id or "",
                ad_account_id=payload.ad_account_id or "",
                lead_form_id=payload.lead_form_id or "",
                meta_connection_id=payload.meta_connection_id,
                campaign_name=payload.campaign_name or f"Meta Lead Ads · {project.name}",
                external_campaign_id=payload.external_campaign_id,
                external_adset_id=payload.external_adset_id,
                external_ad_id=payload.external_ad_id,
                instagram_account_id=payload.instagram_account_id,
                page_access_confirmed=payload.page_access_confirmed,
                ad_account_access_confirmed=payload.ad_account_access_confirmed,
                leads_access_confirmed=payload.leads_access_confirmed,
                commit=False,
            )
            updates = [
                services.user_field_update("campaigns_defined", True),
                services.user_field_update(
                    "meta_connection_verified",
                    connection.verification_mode == "real" and connection.verification_status == "succeeded",
                    status="confirmed" if connection.verification_mode == "real" else "deferred",
                ),
            ]
        else:
            updates = [
                services.user_field_update("campaigns_defined", None, status="deferred"),
                services.user_field_update("meta_connection_verified", None, status="deferred"),
            ]

        result = services.apply_field_updates(
            db,
            profile,
            updates,
            allow_authoritative_statuses=True,
            commit=False,
        )
        if result.rejected:
            raise HTTPException(status_code=422, detail="The onboarding action could not be applied safely.")
        services.record_message_response(
            db,
            project.session.id,
            question.id,
            user_message.content,
            status="accepted",
            commit=False,
        )
        assistant_text = conversational_acknowledgement(
            accepted=result.accepted,
            label_for=lambda field: FIELD_BY_KEY[field].label,
            next_prompt=_next_prompt(profile),
            first_name=current_user.first_name,
            scope="sales activation",
        )
        ai_message = services.save_message(
            db,
            project.session.id,
            SenderType.AI,
            assistant_text,
            ui_payload=_next_question(profile),
            in_reply_to_message_id=user_message.id,
            commit=False,
        )
        db.commit()
        for item in (profile, user_message, ai_message):
            db.refresh(item)
    except Exception:
        db.rollback()
        raise

    return _turn_payload(
        request_id=request_id,
        ai_message=ai_message,
        user_message=user_message,
        profile=profile,
        accepted=result.accepted,
    )


@router.post("/{project_id}/chat/bootstrap", response_model=ChatTurnResponse, status_code=202)
async def bootstrap_chat(
    project_id: str,
    payload: ChatBootstrapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    existing = (
        db.query(ProjectMessage)
        .options(joinedload(ProjectMessage.attachments))
        .filter(ProjectMessage.session_id == project.session.id)
        .order_by(ProjectMessage.created_at.desc())
        .first()
    )
    if existing:
        if existing.sender != SenderType.AI:
            raise HTTPException(status_code=409, detail="The initial message is still being processed.")
        profile = services.get_profile(project)
        previous_user = (
            db.query(ProjectMessage)
            .options(joinedload(ProjectMessage.attachments))
            .filter(
                ProjectMessage.session_id == project.session.id,
                ProjectMessage.sender == SenderType.USER,
                ProjectMessage.created_at <= existing.created_at,
            )
            .order_by(ProjectMessage.created_at.desc())
            .first()
        )
        sources = (
            db.query(ProjectOnboardingSource)
            .filter(ProjectOnboardingSource.message_id == previous_user.id)
            .all()
        ) if previous_user else []
        return {
            "message": _message(existing), "profile": services.serialize_profile(profile),
            "user_message": _message(previous_user) if previous_user else None,
            "accepted_fields": [], "rejected_updates": [],
            "sources": [source_service.serialize_source(source) for source in sources],
            "next_question": _next_question(profile),
        }
    if payload.initial_url and not payload.skip_website:
        profile = services.get_profile(project)
        url = str(payload.initial_url)
        try:
            user_message = services.save_message(
                db, project.session.id, SenderType.USER, url, commit=False,
            )
            source = source_service.create_url_source(
                db, project_id=project.id, user_id=current_user.id, url=url,
                message_id=user_message.id, commit=False,
            )
            job = job_service.enqueue(
                db, scope="project", company_id=current_user.company_id, project_id=project.id,
                source_id=source.id, url=url, session_id=project.session.id,
                message_id=user_message.id, commit=False,
            )
            source = job_service.deduplicate_source(db, job, source, commit=False)
            status_message = services.save_message(
                db, project.session.id, SenderType.AI,
                f"I'm processing **{source.name}** now. You can keep this page open or return later; the result will appear automatically.",
                in_reply_to_message_id=user_message.id,
                commit=False,
            )
            db.commit()
            for item in (user_message, source, status_message):
                db.refresh(item)
        except Exception:
            db.rollback()
            raise
        return {
            "message": _message(status_message), "user_message": _message(user_message),
            "profile": services.serialize_profile(profile), "accepted_fields": [], "rejected_updates": [],
            "sources": [source_service.serialize_source(source)], "next_question": _next_question(profile),
        }
    return start_chat(project_id, db, current_user)


@router.post("/{project_id}/chat/start", response_model=ChatTurnResponse)
def start_chat(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    profile = services.get_profile(project)
    existing = db.query(ProjectMessage).filter(ProjectMessage.session_id == project.session.id).order_by(ProjectMessage.created_at.desc()).first()
    if existing and existing.sender == SenderType.AI:
        message = existing
    elif existing:
        raise HTTPException(status_code=409, detail="The conversation has already started.")
    else:
        first_name = (current_user.first_name or "there").strip()
        intro = (
            f"Welcome, **{first_name}**. I'll help you prepare **{project.name}** as a reliable Project Profile and then verify what is still needed for sales activation.\n\n"
            f"I already have the details used when this project was created. {_next_prompt(profile)} You can also paste a project URL or attach brochures, price lists, inventory spreadsheets, floor plans, or photos; extracted details will stay pending until you review them."
        )
        message = services.save_message(
            db, project.session.id, SenderType.AI, intro,
            ui_payload=_next_question(profile),
        )
    return {"message": _message(message), "profile": services.serialize_profile(profile), "accepted_fields": [], "rejected_updates": [], "sources": [], "next_question": _next_question(profile)}


@router.post("/{project_id}/chat", response_model=ChatTurnResponse)
async def send_chat(
    project_id: str,
    payload: ChatMessagePayload,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    request_id = f"req_{uuid.uuid4().hex}"
    response.headers["X-Request-ID"] = request_id
    project = services.get_project(db, project_id, current_user.company_id)
    db.query(ProjectSession).filter(ProjectSession.id == project.session.id).with_for_update().one()
    existing_turn = _existing_turn(
        db,
        project=project,
        client_message_id=payload.client_message_id,
        request_id=request_id,
    )
    if existing_turn:
        return existing_turn

    active_question = services.get_active_question(
        db,
        project.session.id,
        payload.in_reply_to_message_id,
    )
    resolved_question_id = payload.in_reply_to_message_id or (active_question.id if active_question else None)
    user_message = services.save_message(
        db, project.session.id, SenderType.USER, payload.message,
        in_reply_to_message_id=resolved_question_id,
        message_id=payload.client_message_id,
        commit=False,
    )

    resolution = services.resolve_answer_to_question(
        db,
        session_id=project.session.id,
        message_id=resolved_question_id,
        answer=payload.message,
        profile=services.get_profile(project),
    )
    if resolution.handled and not URL_PATTERN.search(payload.message):
        profile = services.get_profile(project)
        if resolution.action == "approve_profile":
            services.record_message_response(
                db,
                project.session.id,
                resolved_question_id,
                payload.message,
                status="accepted",
                commit=False,
            )
            profile = services.complete_onboarding(db, project, current_user.id)
            ai_message = services.save_message(
                db,
                project.session.id,
                SenderType.AI,
                "Your **Project Profile has been approved successfully**.",
                ui_payload=None,
                in_reply_to_message_id=user_message.id,
            )
            result = _turn_payload(
                request_id=request_id,
                ai_message=ai_message,
                user_message=user_message,
                profile=profile,
                assistant_status="deterministic",
            )
            result["redirect_url"] = f"/app/projects/{project.id}"
            return result

        deterministic_result = services.apply_field_updates(
            db,
            profile,
            resolution.updates,
            allow_authoritative_statuses=current_user.role in EDITOR_ROLES,
            commit=False,
        ) if resolution.updates else services.ApplyUpdatesResult([], [])
        accepted = deterministic_result.accepted
        rejected = deterministic_result.rejected
        accepted_resolution = resolution.status == "accepted" and (bool(accepted) or resolution.action == "request_changes")
        services.record_message_response(
            db,
            project.session.id,
            resolved_question_id,
            payload.message,
            status="accepted" if accepted_resolution else "rejected",
            commit=False,
        )
        if accepted:
            assistant_text = conversational_acknowledgement(
                accepted=accepted,
                label_for=lambda field: FIELD_BY_KEY[field].label,
                next_prompt=_next_prompt(profile),
                first_name=current_user.first_name,
                scope="Project Profile",
            )
        elif resolution.action == "request_changes":
            assistant_text = "Tell me which Project Profile field you want to change."
        else:
            explanations = {
                "invalid_question": "That question is no longer available.",
                "stale_question": "That question is no longer the active step.",
                "empty_answer": "Please enter a value before continuing.",
                "minimum_words": "Please provide a more complete answer.",
                "minimum_characters": "Please provide a more complete answer.",
                "explicit_consent_required": "Use the authorization button so your consent is recorded explicitly.",
                "sales_team_required": "Assign at least one active Sales user, or choose to configure the team later.",
                "meta_setup_required": "Complete the guided Meta setup test, or choose to configure Meta later.",
            }
            assistant_text = explanations.get(
                resolution.reason or "",
                "I couldn't safely apply that answer.",
            ) + " " + _next_prompt(profile)
        ai_message = services.save_message(
            db,
            project.session.id,
            SenderType.AI,
            assistant_text,
            ui_payload=_next_question(profile),
            in_reply_to_message_id=user_message.id,
            commit=False,
        )
        db.commit()
        for item in (user_message, ai_message, profile):
            db.refresh(item)
        return _turn_payload(
            request_id=request_id,
            ai_message=ai_message,
            user_message=user_message,
            profile=profile,
            accepted=accepted,
            rejected=rejected or ([{"update": {"field": active_question.ui_payload.get("field") if active_question else None}, "reason": resolution.reason or "invalid_answer"}] if not accepted_resolution else []),
            assistant_status="deterministic",
        )

    db.commit()
    db.refresh(user_message)
    sources, source_errors = [], []
    for raw_url in URL_PATTERN.findall(payload.message)[:3]:
        url = raw_url.rstrip(".,;:!?)\"]}")
        try:
            source = source_service.create_url_source(
                db, project_id=project.id, user_id=current_user.id, url=url,
                message_id=user_message.id, commit=False,
            )
            job = job_service.enqueue(
                db, scope="project", company_id=current_user.company_id, project_id=project.id,
                source_id=source.id, url=url, session_id=project.session.id,
                message_id=user_message.id, commit=False,
            )
            source = job_service.deduplicate_source(db, job, source, commit=False)
            db.commit()
            db.refresh(source)
            sources.append(source)
        except HTTPException as exc:
            db.rollback()
            source_errors.append({"url": url, "error": exc.detail})
        except Exception:
            db.rollback()
            raise
    return await _complete_chat_turn(
        db=db, project=project, current_user=current_user, user_message=user_message,
        sources=sources, source_errors=source_errors, request_id=request_id,
    )


@router.post("/{project_id}/chat/with-files", response_model=ChatTurnResponse, status_code=202)
async def send_chat_with_files(
    project_id: str,
    response: Response,
    message: str = Form(""),
    in_reply_to_message_id: str | None = Form(None),
    client_message_id: str | None = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    request_id = f"req_{uuid.uuid4().hex}"
    response.headers["X-Request-ID"] = request_id
    project = services.get_project(db, project_id, current_user.company_id)
    db.query(ProjectSession).filter(ProjectSession.id == project.session.id).with_for_update().one()
    existing_turn = _existing_turn(
        db,
        project=project,
        client_message_id=client_message_id,
        request_id=request_id,
    )
    if existing_turn:
        return existing_turn
    clean_message = message.strip()
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    if len(clean_message) > 20000:
        raise HTTPException(status_code=422, detail="The message is too long.")
    visible_message = clean_message or f"Attached {len(files)} project file{'s' if len(files) != 1 else ''}."
    user_message = services.save_message(
        db, project.session.id, SenderType.USER, visible_message,
        in_reply_to_message_id=in_reply_to_message_id,
        message_id=client_message_id,
    )
    sources, source_errors = [], []
    for raw_url in URL_PATTERN.findall(clean_message)[:3]:
        url = raw_url.rstrip(".,;:!?)\"]}")
        try:
            source = source_service.create_url_source(
                db, project_id=project.id, user_id=current_user.id, url=url,
                message_id=user_message.id, commit=False,
            )
            job = job_service.enqueue(
                db, scope="project", company_id=current_user.company_id, project_id=project.id,
                source_id=source.id, url=url, session_id=project.session.id,
                message_id=user_message.id, commit=False,
            )
            source = job_service.deduplicate_source(db, job, source, commit=False)
            db.commit()
            db.refresh(source)
            sources.append(source)
        except HTTPException as exc:
            db.rollback()
            source_errors.append({"url": url, "error": exc.detail})
        except Exception:
            db.rollback()
            raise
    for upload in files:
        source = await source_service.create_file_source(
            db, project_id=project.id, company_id=current_user.company_id,
            user_id=current_user.id, upload=upload, message_id=user_message.id,
        )
        sources.append(source)
        if source.status.value == "processing":
            job_service.enqueue(
                db,
                scope="project",
                company_id=current_user.company_id,
                project_id=project.id,
                source_id=source.id,
                url=source_service.file_job_url(source),
                session_id=project.session.id,
                message_id=user_message.id,
            )
        else:
            source_errors.append({"file": source.name, "error": source.error_message})
    return await _complete_chat_turn(
        db=db, project=project, current_user=current_user, user_message=user_message,
        sources=sources, source_errors=source_errors, request_id=request_id,
    )


@router.get("/{project_id}/sources", response_model=list[SourceResponse])
def list_sources(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    services.get_project(db, project_id, current_user.company_id)
    sources = db.query(ProjectOnboardingSource).filter(ProjectOnboardingSource.project_id == project_id).order_by(ProjectOnboardingSource.created_at.desc()).all()
    return [source_service.serialize_source(source) for source in sources]


@router.post("/{project_id}/sources/url", response_model=SourceResponse, status_code=202)
async def add_url(project_id: str, payload: UrlSourceRequest, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    try:
        source = source_service.create_url_source(
            db, project_id=project_id, user_id=current_user.id,
            url=str(payload.url), commit=False,
        )
        job = job_service.enqueue(
            db, scope="project", company_id=current_user.company_id, project_id=project.id,
            source_id=source.id, url=str(payload.url), session_id=project.session.id,
            commit=False,
        )
        source = job_service.deduplicate_source(db, job, source, commit=False)
        db.commit()
        db.refresh(source)
    except Exception:
        db.rollback()
        raise
    return source_service.serialize_source(source)


@router.post("/{project_id}/sources/files", response_model=list[SourceResponse], status_code=202)
async def add_files(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    user_message = services.save_message(
        db,
        project.session.id,
        SenderType.USER,
        f"Attached {len(files)} project file{'s' if len(files) != 1 else ''}.",
    )
    sources = []
    for upload in files:
        source = await source_service.create_file_source(
            db, project_id=project_id, company_id=current_user.company_id,
            user_id=current_user.id, upload=upload, message_id=user_message.id,
        )
        sources.append(source)
        if source.status.value == "processing":
            job_service.enqueue(
                db,
                scope="project",
                company_id=current_user.company_id,
                project_id=project.id,
                source_id=source.id,
                url=source_service.file_job_url(source),
                session_id=project.session.id,
                message_id=user_message.id,
            )
    if not any(source.status.value == "processing" for source in sources):
        finalize_source_group(
            db,
            scope="project",
            company_id=current_user.company_id,
            project_id=project.id,
            message_id=user_message.id,
        )
        db.commit()
    return [source_service.serialize_source(source) for source in sources]


@router.post("/{project_id}/sources/{source_id}/retry", response_model=SourceResponse, status_code=202)
def retry_url_source(
    project_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    services.get_project(db, project_id, current_user.company_id)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == source_id,
        ProjectOnboardingSource.project_id == project_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    if not source.url and not source.storage_path:
        raise HTTPException(status_code=409, detail="This source has no recoverable location.")
    if not job_service.retry_job(db, scope="project", source_id=source.id):
        raise HTTPException(status_code=409, detail="This source has no recoverable job.")
    source.status = source.status.__class__.PROCESSING
    source.error_message = None
    db.add(source)
    db.commit()
    db.refresh(source)
    return source_service.serialize_source(source)


@router.get("/{project_id}/sources/{source_id}/file")
def download_source_file(
    project_id: str, source_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    services.get_project(db, project_id, current_user.company_id)
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == source_id,
        ProjectOnboardingSource.project_id == project_id,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="File not found.")
    try:
        path = storage_service.resolve_project_file(source.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path, media_type=source.mime_type or "application/octet-stream",
        filename=source.original_filename or source.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{project_id}/proposals/{proposal_id}/decision", response_model=ProposalDecisionResponse)
def decide_proposal(project_id: str, proposal_id: str, payload: ProposalDecision, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    services.get_project(db, project_id, current_user.company_id)
    proposal = db.query(ProjectOnboardingProposal).join(ProjectOnboardingSource).filter(ProjectOnboardingProposal.id == proposal_id, ProjectOnboardingSource.project_id == project_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    proposal, profile = source_service.review_proposal(db, proposal=proposal, company_id=current_user.company_id, user_id=current_user.id, action=payload.action, corrected_value=payload.value)
    _continue_after_source_review(db, proposal=proposal, profile=profile)
    db.commit()
    db.refresh(proposal)
    return {"proposal": source_service.serialize_proposal(proposal), "profile": services.serialize_profile(profile)}


@router.get("/{project_id}/campaigns", response_model=list[CampaignResponse])
def list_campaigns(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    services.get_project(db, project_id, current_user.company_id)
    return db.query(ProjectCampaign).filter(ProjectCampaign.project_id == project_id).all()


@router.get("/{project_id}/marketing/summary", response_model=ProjectMarketingSummary)
def project_marketing_summary(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(VIEWER_ROLES)),
):
    from app.modules.sales_crm.models import FunnelStage, Lead, Meeting

    project = services.get_project(db, project_id, current_user.company_id)
    campaigns = db.query(ProjectCampaign).filter(ProjectCampaign.project_id == project.id).order_by(ProjectCampaign.created_at).all()
    leads = db.query(Lead).filter(Lead.project_id == project.id, Lead.company_id == current_user.company_id).all()
    meetings = db.query(Meeting).filter(Meeting.project_id == project.id).all()
    lead_ids_with_meetings = {meeting.lead_id for meeting in meetings}
    campaign_by_id = {campaign.id: campaign for campaign in campaigns}
    campaign_metrics = []
    for campaign in campaigns:
        campaign_leads = [lead for lead in leads if lead.campaign_id == campaign.id]
        qualified = sum(lead.funnel_stage in {FunnelStage.QUALIFIED, FunnelStage.APPOINTMENT_SET, FunnelStage.CLOSED} for lead in campaign_leads)
        appointments = sum(lead.id in lead_ids_with_meetings for lead in campaign_leads)
        campaign_metrics.append({
            "id": campaign.id, "name": campaign.name, "platform": campaign.platform, "status": campaign.status,
            "leads": len(campaign_leads), "qualified": qualified, "appointments": appointments,
            "conversion_rate": round(100 * appointments / len(campaign_leads), 2) if campaign_leads else 0,
        })
    qualified_total = sum(lead.funnel_stage in {FunnelStage.QUALIFIED, FunnelStage.APPOINTMENT_SET, FunnelStage.CLOSED} for lead in leads)
    appointments_total = sum(lead.id in lead_ids_with_meetings for lead in leads)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "totals": {
            "campaigns": len(campaigns), "active_campaigns": sum(item.status == "active" for item in campaigns),
            "leads": len(leads), "qualified": qualified_total, "appointments": appointments_total,
            "conversion_rate": round(100 * appointments_total / len(leads), 2) if leads else 0,
            "high_intent": sum(float(lead.intent_score or 0) >= 0.75 for lead in leads),
            "pending_follow_up": sum(lead.next_action_at is not None for lead in leads),
            "follow_up_rate": round(100 * sum(lead.last_interaction_at is not None for lead in leads) / len(leads), 1) if leads else 0,
        },
        "campaigns": campaign_metrics,
        "intent_distribution": {
            tier: sum(lead.intent_tier == tier for lead in leads)
            for tier in ("hot", "warm", "cold", "unscored")
        },
        "segment_distribution": {
            segment: sum(lead.assigned_segment == segment for lead in leads)
            for segment in sorted({lead.assigned_segment for lead in leads if lead.assigned_segment})
        },
        "leads": [{
            "id": lead.id, "full_name": lead.full_name, "email": lead.email, "phone": lead.phone,
            "campaign_id": lead.campaign_id,
            "campaign_name": campaign_by_id.get(lead.campaign_id).name if lead.campaign_id in campaign_by_id else "Unattributed",
            "funnel_stage": lead.funnel_stage.value, "intent_score": float(lead.intent_score or 0),
            "last_interaction_at": lead.last_interaction_at, "next_action_at": lead.next_action_at,
            "agent_status": lead.agent_status, "qualification_summary": lead.qualification_summary,
            "intent_tier": lead.intent_tier, "assigned_segment": lead.assigned_segment,
            "pipeline_stage": lead.pipeline_stage,
            "is_opt_out": lead.is_opt_out, "created_at": lead.created_at,
        } for lead in leads],
    }


@router.post("/{project_id}/campaigns", response_model=CampaignResponse, status_code=201)
def create_campaign(project_id: str, payload: CampaignCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    if payload.meta_connection_id:
        connection = db.query(MetaConnection).filter(MetaConnection.id == payload.meta_connection_id, MetaConnection.company_id == current_user.company_id).first()
        if not connection:
            raise HTTPException(status_code=404, detail="Meta connection not found.")
    campaign = ProjectCampaign(project_id=project.id, **payload.model_dump())
    db.add(campaign); db.commit(); db.refresh(campaign)
    updates = [{
        "field": "campaigns_defined", "value": True, "status": "confirmed",
        "applicable": True, "source_type": "campaign_configuration",
        "source_reference": campaign.id, "confidence": "high",
    }]
    if payload.meta_connection_id and connection.verified_at:
        updates.append({
            "field": "meta_connection_verified", "value": True, "status": "confirmed",
            "applicable": True, "source_type": "meta_verification",
            "source_reference": connection.id, "confidence": "high",
        })
    services.apply_field_updates(
        db, services.get_profile(project), updates,
        allow_authoritative_statuses=current_user.role in TENANT_MANAGER_ROLES,
    )
    return campaign


@router.get("/{project_id}/meta-setup/config", response_model=MetaSetupConfigurationResponse)
def get_meta_setup_configuration(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    services.get_project(db, project_id, current_user.company_id)
    partner_id = settings.META_BUSINESS_MANAGER_ID.strip() or None
    return {"partner_business_manager_id": partner_id, "configured": partner_id is not None}


@router.post("/{project_id}/meta-setup/simulate", response_model=MetaProjectSetupResponse)
def simulate_meta_project_setup(
    project_id: str,
    payload: MetaProjectSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    partner_id = settings.META_BUSINESS_MANAGER_ID.strip() or None
    if not partner_id:
        raise HTTPException(
            status_code=503,
            detail="Black Penguin's Meta Business Manager ID is not configured yet.",
        )
    try:
        connection, campaign = meta_service.simulate_project_setup(
            db,
            project=project,
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "connection": connection,
        "campaign": campaign,
        "simulated": connection.verification_mode == "simulated",
        "success": True,
        "message": (
            "Verified Company Meta connection assigned to the Project."
            if connection.verification_mode == "real"
            else "Simulated connection successful. Live Meta access must still be verified before activation."
        ),
        "partner_business_manager_id": partner_id,
    }


@router.get("/integrations/meta/connections", response_model=list[MetaConnectionResponse])
def list_meta_connections(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    return db.query(MetaConnection).filter(MetaConnection.company_id == current_user.company_id).all()


@router.post("/integrations/meta/connections", response_model=MetaConnectionResponse, status_code=201)
def create_meta_connection(payload: MetaConnectionCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    return meta_service.create_connection(db, company_id=current_user.company_id, payload=payload.model_dump())


@router.post("/integrations/meta/connections/{connection_id}/verify", response_model=MetaConnectionResponse)
async def verify_meta_connection(connection_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    connection = db.query(MetaConnection).filter(MetaConnection.id == connection_id, MetaConnection.company_id == current_user.company_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Meta connection not found.")
    try:
        verified = await meta_service.verify_connection(db, connection)
        campaigns = (
            db.query(ProjectCampaign)
            .join(Project)
            .filter(
                ProjectCampaign.meta_connection_id == verified.id,
                Project.company_id == current_user.company_id,
            )
            .all()
        )
        for campaign in campaigns:
            services.apply_field_updates(
                db, services.get_profile(campaign.project), [{
                    "field": "meta_connection_verified", "value": True,
                    "status": "confirmed", "applicable": True,
                    "source_type": "meta_verification", "source_reference": verified.id,
                    "confidence": "high",
                }], allow_authoritative_statuses=True,
            )
        return verified
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Meta could not verify this access token.") from exc
