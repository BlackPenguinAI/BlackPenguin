from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
import httpx
from sqlalchemy.orm import Session, joinedload

from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.onboarding_questions import build_next_question
from app.modules.onboarding_jobs import service as job_service
from app.modules.onboarding_jobs.continuation import finalize_source_group
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.users.models import User, UserRole

from . import meta_service, services, source_service, storage_service
from .completion import FIELD_BY_KEY
from .models import (
    MetaConnection, Project, ProjectCampaign, ProjectMessage, ProjectOnboardingProposal,
    ProjectOnboardingSource, ProjectSession, ProjectSourceKind, SenderType,
)
from .schemas import (
    CampaignCreate, CampaignResponse, ChatBootstrapRequest, ChatMessagePayload, ChatMessageResponse, ChatTurnResponse,
    MetaConnectionCreate, MetaConnectionResponse, ProjectCreate, ProjectProfilePatch,
    ProjectCompleteResponse, ProjectDeleteRequest, ProjectDeletionImpact, ProjectDraftResponse,
    ProjectOverviewResponse, ProjectProfileResponse, ProjectResponse,
    OnboardingStateResponse, ProposalDecision, ProposalDecisionResponse,
    SourceResponse, UrlSourceRequest,
)
from app.modules.demo_projects.service import provision_demo_project


router = APIRouter()
EDITOR_ROLES = [UserRole.ADMIN, UserRole.MKT]
VIEWER_ROLES = [UserRole.ADMIN, UserRole.MKT, UserRole.SALES]
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


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


def _next_prompt(profile) -> str:
    return _next_question(profile)["prompt"]


def _next_question(profile) -> dict[str, Any]:
    blockers = services.serialize_profile(profile)["completion"]["blockers"]
    return build_next_question(
        blockers,
        final_prompt="Review the Project Profile and choose whether to approve it or make changes.",
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
        if latest_ai and not latest_ai.ui_payload and not latest_ai.response_payload:
            latest_ai.ui_payload = _next_question(profile)
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
            "message": _message(ai_message),
            "user_message": _message(user_message),
            "profile": services.serialize_profile(profile),
            "accepted_fields": [],
            "rejected_updates": [],
            "sources": [source_service.serialize_source(source) for source in sources],
            "next_question": _next_question(profile),
        }
    ai_config = get_ai_config(db, current_user.company_id)
    if not ai_config.openrouter_api_key:
        raise HTTPException(status_code=500, detail="AI configuration is incomplete.")
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
    try:
        raw = await generate_llm_response(
            ai_config.openrouter_api_key, model, messages,
            response_format={"type": "json_object"}, temperature=0.25, raise_on_error=True,
        )
        parsed = _parse_agent_response(raw)
        if parsed is None:
            repaired = await generate_llm_response(
                ai_config.openrouter_api_key, model,
                messages + [{"role": "assistant", "content": raw}, {"role": "system", "content": "Repair the response and return only valid contract JSON."}],
                response_format={"type": "json_object"}, temperature=0, raise_on_error=True,
            )
            parsed = _parse_agent_response(repaired)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The project assistant is temporarily unavailable.") from exc

    if parsed is None:
        assistant_text, updates, approved = "I couldn't validate my response, so I left the Project Profile unchanged. " + _next_prompt(profile), [], None
    else:
        assistant_text, updates, approved = parsed
    result = services.apply_field_updates(
        db, profile, updates, allow_authoritative_statuses=current_user.role == UserRole.ADMIN,
        final_approved=None,
    )
    if result.accepted:
        labels = [FIELD_BY_KEY[item["field"]].label for item in result.accepted]
        assistant_text = "I validated and updated: " + ", ".join(f"**{label}**" for label in labels) + ".\n\n" + _next_prompt(profile)
    elif result.rejected:
        assistant_text = "I couldn't safely apply that information, so nothing was changed. " + _next_prompt(profile)
    ai_message = services.save_message(
        db, project.session.id, SenderType.AI, assistant_text,
        ui_payload=_next_question(profile),
        in_reply_to_message_id=user_message.id,
    )
    db.refresh(user_message)
    return {
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
    ).order_by(Project.created_at.desc()).all()
    return [services.serialize_project(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    return services.serialize_project(services.get_project(db, project_id, current_user.company_id))


@router.get("/{project_id}/overview", response_model=ProjectOverviewResponse)
def get_project_overview(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(VIEWER_ROLES)),
):
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
    db.add(source); db.commit(); db.refresh(source)
    return source_service.serialize_source(source)


@router.get("/{project_id}/deletion-impact", response_model=ProjectDeletionImpact)
def get_deletion_impact(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return services.deletion_impact(db, project)


@router.post("/{project_id}/archive", response_model=ProjectResponse)
def archive_project(
    project_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    project = services.get_project(db, project_id, current_user.company_id)
    return services.serialize_project(services.archive_project(db, project))


@router.post("/{project_id}/demo/reset", response_model=ProjectResponse)
def reset_demo_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    project = services.get_project(db, project_id, current_user.company_id)
    if not project.is_demo:
        raise HTTPException(status_code=409, detail="Only the Demo Project can be reset.")
    try:
        project = provision_demo_project(
            db,
            company_id=current_user.company_id,
            approved_by_user_id=current_user.id,
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
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    project = services.get_project(db, project_id, current_user.company_id)
    services.delete_project(db, project, confirm_name=payload.confirm_name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/profile", response_model=ProjectProfileResponse)
def get_profile(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(VIEWER_ROLES))):
    return services.serialize_profile(services.get_profile(services.get_project(db, project_id, current_user.company_id)))


@router.patch("/{project_id}/profile", response_model=ProjectProfileResponse)
def patch_profile(project_id: str, payload: ProjectProfilePatch, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
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
async def send_chat(project_id: str, payload: ChatMessagePayload, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    project = services.get_project(db, project_id, current_user.company_id)
    services.record_message_response(db, project.session.id, payload.in_reply_to_message_id, payload.message)
    user_message = services.save_message(
        db, project.session.id, SenderType.USER, payload.message,
        in_reply_to_message_id=payload.in_reply_to_message_id,
    )
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
        sources=sources, source_errors=source_errors,
    )


@router.post("/{project_id}/chat/with-files", response_model=ChatTurnResponse)
async def send_chat_with_files(
    project_id: str,
    message: str = Form(""),
    in_reply_to_message_id: str | None = Form(None),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(EDITOR_ROLES)),
):
    project = services.get_project(db, project_id, current_user.company_id)
    clean_message = message.strip()
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    if len(clean_message) > 20000:
        raise HTTPException(status_code=422, detail="The message is too long.")
    visible_message = clean_message or f"Attached {len(files)} project file{'s' if len(files) != 1 else ''}."
    services.record_message_response(db, project.session.id, in_reply_to_message_id, visible_message)
    user_message = services.save_message(
        db, project.session.id, SenderType.USER, visible_message,
        in_reply_to_message_id=in_reply_to_message_id,
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
        source = await source_service.ingest_file(
            db, project_id=project.id, company_id=current_user.company_id,
            user_id=current_user.id, upload=upload, message_id=user_message.id,
        )
        sources.append(source)
        if source.status.value == "failed":
            source_errors.append({"file": source.name, "error": source.error_message})
    return await _complete_chat_turn(
        db=db, project=project, current_user=current_user, user_message=user_message,
        sources=sources, source_errors=source_errors,
    )


@router.get("/{project_id}/sources", response_model=list[SourceResponse])
def list_sources(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker(EDITOR_ROLES))):
    services.get_project(db, project_id, current_user.company_id)
    sources = db.query(ProjectOnboardingSource).filter(ProjectOnboardingSource.project_id == project_id).order_by(ProjectOnboardingSource.created_at.desc()).all()
    return [source_service.serialize_source(source) for source in sources]


@router.post("/{project_id}/sources/url", response_model=SourceResponse, status_code=202)
async def add_url(project_id: str, payload: UrlSourceRequest, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
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


@router.post("/{project_id}/sources/files", response_model=list[SourceResponse])
async def add_files(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
    project = services.get_project(db, project_id, current_user.company_id)
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    user_message = services.save_message(
        db,
        project.session.id,
        SenderType.USER,
        f"Attached {len(files)} project file{'s' if len(files) != 1 else ''}.",
    )
    sources = [await source_service.ingest_file(
        db, project_id=project_id, company_id=current_user.company_id,
        user_id=current_user.id, upload=file, message_id=user_message.id,
    ) for file in files]
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
    if not source.url:
        raise HTTPException(status_code=409, detail="This source has no URL to retry.")
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
def decide_proposal(project_id: str, proposal_id: str, payload: ProposalDecision, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
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
        allow_authoritative_statuses=current_user.role == UserRole.ADMIN,
    )
    return campaign


@router.get("/integrations/meta/connections", response_model=list[MetaConnectionResponse])
def list_meta_connections(db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
    return db.query(MetaConnection).filter(MetaConnection.company_id == current_user.company_id).all()


@router.post("/integrations/meta/connections", response_model=MetaConnectionResponse, status_code=201)
def create_meta_connection(payload: MetaConnectionCreate, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
    return meta_service.create_connection(db, company_id=current_user.company_id, payload=payload.model_dump())


@router.post("/integrations/meta/connections/{connection_id}/verify", response_model=MetaConnectionResponse)
async def verify_meta_connection(connection_id: str, db: Session = Depends(get_db), current_user: User = Depends(RoleChecker([UserRole.ADMIN]))):
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
