from __future__ import annotations

import json
import re
from typing import Any
import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.companies.models import Company
from app.modules.onboarding_questions import build_next_question
from app.modules.onboarding_jobs import service as job_service
from app.modules.onboarding_jobs.continuation import finalize_source_group
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_copy import conversational_acknowledgement
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users import services as user_services

from . import overview_service, services, source_service, storage_service
from .completion import FIELD_BY_KEY
from .models import (
    CompanyOnboardingProposal,
    CompanyOnboardingSource,
    CompanyMediaAsset,
    OnboardingMessage,
    OnboardingSession,
    SenderType,
)
from .schemas import (
    ChatBootstrapRequest,
    ChatMessagePayload,
    ChatMessageResponse,
    ChatTurnResponse,
    CompanyProfilePatch,
    CompanyProfileResponse,
    CompanyMediaAssetResponse,
    CompanyOverviewResponse,
    OnboardingStateResponse,
    ProposalDecision,
    ProposalDecisionResponse,
    ScrapeRequest,
    SessionResponse,
    SourceResponse,
    TeamMemberCreate,
    TeamMemberResponse,
    TeamOnboardingResponse,
    TeamRoleDecision,
)


router = APIRouter()
ALLOWED_ROLES = [*TENANT_MANAGER_ROLES, UserRole.MKT]
USER_FACING_JSON_VALUE = re.compile(
    r"(?P<prefix>\*\*[^*\n]+:\*\*\s*)(?P<value>\[[^\n]*\]|\{[^\n]*\})"
)


@router.get("/overview", response_model=CompanyOverviewResponse)
def get_company_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    profile = services.get_or_create_profile(db, current_user.company_id)
    if not services.serialize_profile(profile)["completion"]["can_complete"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "company_onboarding_incomplete",
                "message": "Complete and approve Company Onboarding before opening Company Overview.",
                "redirect_url": "/app/company/onboarding",
            },
        )
    return overview_service.overview(db, current_user.company_id)


@router.get("/media", response_model=list[CompanyMediaAssetResponse])
def list_company_media(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    assets = db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.company_id == current_user.company_id,
        CompanyMediaAsset.review_status != "rejected",
    ).order_by(CompanyMediaAsset.is_primary.desc(), CompanyMediaAsset.created_at).all()
    return [overview_service.serialize_asset(asset) for asset in assets]


@router.post("/media/logo", response_model=CompanyMediaAssetResponse, status_code=201)
async def upload_company_logo(
    file: UploadFile = File(...), db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    asset = await source_service.ingest_logo_upload(
        db, company_id=current_user.company_id, user_id=current_user.id, upload=file,
    )
    return overview_service.serialize_asset(asset)


@router.post("/media/{asset_id}/logo", response_model=CompanyMediaAssetResponse)
def select_company_logo(
    asset_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    asset = db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.id == asset_id,
        CompanyMediaAsset.company_id == current_user.company_id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Company image not found.")
    db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.company_id == current_user.company_id,
    ).update({CompanyMediaAsset.is_primary: False}, synchronize_session=False)
    asset.is_primary = True; asset.role = "logo"; asset.review_status = "confirmed"
    profile = services.get_or_create_profile(db, current_user.company_id)
    services.apply_field_updates(db, profile, [{
        "field": "company_logo", "value": asset.id, "status": "confirmed", "applicable": True,
        "source_type": "media_selection", "source_reference": asset.source_url or asset.name, "confidence": "high",
    }], allow_authoritative_statuses=True)
    db.add(asset); db.commit(); db.refresh(asset)
    return overview_service.serialize_asset(asset)


@router.get("/media/{asset_id}/file")
def get_company_media_file(
    asset_id: str, db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    asset = db.query(CompanyMediaAsset).filter(
        CompanyMediaAsset.id == asset_id,
        CompanyMediaAsset.company_id == current_user.company_id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Company image not found.")
    try:
        path = storage_service.resolve_company_file(asset.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Company image not found.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Company image not found.")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.name,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


def _is_authorized_admin(user: User) -> bool:
    return user.role in TENANT_MANAGER_ROLES


def _parse_agent_response(raw: str) -> tuple[str, list[dict[str, Any]], bool | None] | None:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("assistant_message"), str):
        return None
    updates = payload.get("verified_updates", [])
    if not isinstance(updates, list) or any(not isinstance(item, dict) for item in updates):
        return None
    final_approved = payload.get("final_approved")
    if not isinstance(final_approved, bool):
        final_approved = None
    return payload["assistant_message"].strip(), updates, final_approved


def _rejected_payload(items: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    return [
        {
            "field": item.get("update", {}).get("field") if isinstance(item.get("update"), dict) else None,
            "reason": item["reason"],
        }
        for item in items
    ]


def _message_payload(message: OnboardingMessage) -> dict[str, Any]:
    content = (
        _normalize_user_facing_content(message.content)
        if message.sender == SenderType.AI
        else message.content
    )
    if (
        message.sender == SenderType.AI
        and message.response_payload
        and message.response_payload.get("status") == "superseded"
        and message.ui_payload
        and isinstance(message.ui_payload.get("prompt"), str)
    ):
        prompt = message.ui_payload["prompt"].strip()
        if prompt and content.rstrip().endswith(prompt):
            content = content.rstrip()[:-len(prompt)].rstrip()
    return {
        "id": message.id,
        "sender": "user" if message.sender == SenderType.USER else "ai",
        "content": content,
        "ui_payload": message.ui_payload,
        "response_payload": message.response_payload,
        "in_reply_to_message_id": message.in_reply_to_message_id,
        "created_at": message.created_at,
        "attachments": [
            {
                "id": source.id, "kind": source.kind.value, "name": source.name,
                "mime_type": source.mime_type, "size_bytes": source.size_bytes,
                "status": source.status.value, "url": source.url,
                "download_url": f"/api/v1/company-onboarding/sources/{source.id}/file" if source.storage_path else None,
            }
            for source in message.attachments
        ],
    }


def _next_prompt(profile) -> str:
    return _next_question(profile)["prompt"]


def _next_question(profile) -> dict[str, Any]:
    completion = services.serialize_profile(profile)["completion"]
    if completion["can_complete"]:
        return {
            "field": None,
            "label": "Company Profile complete",
            "prompt": "Your Company Profile is approved. Continue to Projects when you are ready.",
            "input_type": "complete",
            "options": [],
            "examples": [],
            "allow_custom": False,
            "minimum_words": None,
            "minimum_characters": None,
            "help_text": None,
            "answer_actions": {},
        }
    return build_next_question(
        completion["blockers"],
        final_prompt="Review the Company Profile and choose whether to approve it or make changes.",
        profile_data=profile.profile_data or {},
    )


def _natural_join(values: list[str]) -> str:
    if not values:
        return "None provided"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def _format_user_facing_value(value: Any) -> str:
    if isinstance(value, list):
        return _natural_join([_format_user_facing_value(item) for item in value])
    if isinstance(value, dict):
        if value.get("exists") is False:
            return "No official website"
        if isinstance(value.get("url"), str):
            return value["url"]
        entries = [
            f"{str(key).replace('_', ' ').capitalize()}: {_format_user_facing_value(item)}"
            for key, item in value.items()
            if item is not None
        ]
        return "; ".join(entries) if entries else "Not applicable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "Not applicable"
    return str(value)


def _normalize_user_facing_content(content: str) -> str:
    """Hide legacy JSON list/dict syntax in persisted acknowledgement messages."""
    def replace(match: re.Match[str]) -> str:
        try:
            value = json.loads(match.group("value"))
        except json.JSONDecodeError:
            return match.group(0)
        return match.group("prefix") + _format_user_facing_value(value)

    return USER_FACING_JSON_VALUE.sub(replace, content)


def _accepted_response(
    first_name: str | None,
    accepted: list[dict[str, Any]],
    profile,
    *,
    continuation: str | None = None,
) -> str:
    next_step = _next_prompt(profile) if continuation is None else continuation
    return conversational_acknowledgement(
        accepted=accepted,
        label_for=lambda field: FIELD_BY_KEY[field].label,
        next_prompt=next_step,
        first_name=first_name,
        scope="Company Profile",
    )


def _continue_after_source_review(
    db: Session,
    *,
    proposal: CompanyOnboardingProposal,
    profile,
) -> OnboardingMessage | None:
    return finalize_source_group(
        db,
        scope="company",
        company_id=proposal.source.company_id,
        message_id=proposal.source.message_id,
    )


def _workflow_stage(
    serialized_profile: dict[str, Any],
    team: dict[str, Any],
    *,
    processing: bool,
    pending_review: bool,
    pristine: bool,
) -> str:
    """Return the single server-owned step the Company UI may render."""
    completion = serialized_profile["completion"]
    if completion["can_complete"]:
        return "complete"
    if processing:
        return "processing"
    if pending_review:
        return "website_review"
    if pristine:
        return "website"
    logo = next(
        (field for field in serialized_profile["fields"] if field["key"] == "company_logo"),
        {"status": "missing"},
    )
    if logo["status"] not in {"confirmed", "corrected_by_user", "deferred"}:
        return "logo_review"
    if completion["required"]["remaining"]:
        return "required"
    if any(role["status"] == "missing" for role in team["roles"]):
        return "team"
    if completion["blockers"]:
        return "conditional"
    presence_keys = {
        "public_contact_emails", "public_contact_phones", "corporate_social_profiles",
    }
    presence_fields = [
        field for field in serialized_profile["fields"] if field["key"] in presence_keys
    ]
    if any(field["status"] == "missing" for field in presence_fields):
        return "enrichment"
    return "approval"


CHAT_QUESTION_STAGES = {"required", "conditional", "approval"}


def _logo_question() -> dict[str, Any]:
    return {
        "field": "company_logo",
        "label": "Company logo",
        "prompt": "Choose the official Company logo and confirm your selection.",
        "input_type": "company_logo",
        "options": [],
        "examples": [],
        "allow_custom": False,
        "minimum_words": None,
        "minimum_characters": None,
        "help_text": "Select a website candidate, upload the official logo, or provide it later.",
        "answer_actions": {},
    }


def _stage_next_question(stage: str, profile) -> dict[str, Any] | None:
    """Expose a chat question only while the chat is the active workflow control."""
    if stage == "logo_review":
        return _logo_question()
    return _next_question(profile) if stage in CHAT_QUESTION_STAGES else None


def _stage_continuation(stage: str, profile) -> str:
    if stage in CHAT_QUESTION_STAGES:
        return _next_prompt(profile)
    if stage == "team":
        return (
            "The required Company Profile is complete. Add Company users now, "
            "or continue and invite them later."
        )
    if stage == "logo_review":
        return "Next, choose and confirm the official Company logo, or provide it later."
    if stage == "enrichment":
        return "Next, review the company's public contact information and social media."
    if stage == "complete":
        return "Your Company Profile is approved. Continue to Projects when you are ready."
    return ""


def _runtime_workflow_stage(
    db: Session,
    company_id: str,
    profile,
    *,
    processing: bool = False,
) -> str:
    sources = (
        db.query(CompanyOnboardingSource)
        .filter(CompanyOnboardingSource.company_id == company_id)
        .all()
    )
    pending_review = any(
        proposal.status.value == "pending"
        for source in sources
        for proposal in source.proposals
    )
    return _workflow_stage(
        services.serialize_profile(profile),
        services.serialize_team(db, company_id, profile),
        processing=processing or any(source.status.value == "processing" for source in sources),
        pending_review=pending_review,
        pristine=False,
    )


def _state_payload(db: Session, company_id: str) -> dict[str, Any]:
    session = services.get_or_create_session(db, company_id)
    profile = services.get_or_create_profile(db, company_id)
    messages = (
        db.query(OnboardingMessage)
        .options(joinedload(OnboardingMessage.attachments))
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
    sources = (
        db.query(CompanyOnboardingSource)
        .filter(CompanyOnboardingSource.company_id == company_id)
        .order_by(CompanyOnboardingSource.created_at.desc())
        .all()
    )
    serialized_profile = services.serialize_profile(profile)
    processing = any(source.status.value == "processing" for source in sources) or db.query(OnboardingSourceJob).filter(
        OnboardingSourceJob.scope == "company",
        OnboardingSourceJob.company_id == company_id,
        OnboardingSourceJob.status.in_(["queued", "processing"]),
    ).first() is not None
    pending_review = any(
        proposal.status.value == "pending"
        for source in sources
        for proposal in source.proposals
    )
    team = services.serialize_team(db, company_id, profile)
    stage = _workflow_stage(
        serialized_profile,
        team,
        processing=processing,
        pending_review=pending_review,
        pristine=not messages and not sources,
    )
    next_question = _stage_next_question(stage, profile)
    if next_question:
        active_question = services.get_active_question(db, session.id)
        latest_ai = next((item for item in reversed(messages) if item.sender == SenderType.AI), None)
        if active_question:
            changed = services.supersede_unanswered_questions(
                db, session.id, keep_message_id=active_question.id,
            )
            if active_question.ui_payload != next_question:
                active_question.ui_payload = next_question
                db.add(active_question)
                changed = True
            if changed:
                db.commit(); db.refresh(active_question)
        elif latest_ai and not latest_ai.ui_payload and not latest_ai.response_payload:
            services.supersede_unanswered_questions(db, session.id)
            latest_ai.ui_payload = next_question
            db.add(latest_ai); db.commit(); db.refresh(latest_ai)
        elif not active_question:
            latest_ai = services.save_message(
                db, session.id, SenderType.AI, next_question["prompt"], ui_payload=next_question,
            )
            messages.append(latest_ai)
    else:
        if services.supersede_unanswered_questions(db, session.id):
            db.commit()
    timestamps = [profile.updated_at, *[item.created_at for item in messages], *[item.updated_at for item in sources]]
    version = int(max((item.timestamp() for item in timestamps if item), default=0) * 1000)
    return {
        "messages": [_message_payload(message) for message in messages],
        "profile": serialized_profile,
        "sources": [source_service.serialize_source(source) for source in sources],
        "next_question": next_question,
        "stage": stage,
        "version": version,
        "team": team,
    }


@router.get("/team", response_model=TeamOnboardingResponse)
def get_onboarding_team(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    return services.serialize_team(db, current_user.company_id)


@router.post("/team/members", response_model=TeamMemberResponse, status_code=201)
def create_onboarding_team_member(
    payload: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    try:
        role = UserRole(payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.") from exc
    user = user_services.invite_tenant_user(
        db,
        company_id=current_user.company_id,
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=role,
    )
    profile = services.get_or_create_profile(db, current_user.company_id)
    services.clear_team_role_decision(db, profile, role)
    return user


@router.patch("/team/roles/{role_name}", response_model=TeamOnboardingResponse)
def decide_onboarding_team_role(
    role_name: str,
    payload: TeamRoleDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    try:
        role = UserRole(role_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.") from exc
    if role not in services.TEAM_ROLE_STATE_KEYS:
        raise HTTPException(status_code=422, detail="Role must be assistant, mkt or sales.")
    profile = services.get_or_create_profile(db, current_user.company_id)
    services.set_team_role_decision(db, profile, role, payload.status)
    return services.serialize_team(db, current_user.company_id, profile)


@router.post("/team/defer-remaining", response_model=TeamOnboardingResponse)
def defer_remaining_onboarding_team_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    profile = services.get_or_create_profile(db, current_user.company_id)
    return services.defer_missing_team_roles(db, current_user.company_id, profile)


@router.post("/team/continue", response_model=OnboardingStateResponse)
def continue_company_onboarding_after_team(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    """Finish the optional Team step and return the next workflow state."""
    profile = services.get_or_create_profile(db, current_user.company_id)
    services.defer_missing_team_roles(db, current_user.company_id, profile)
    return _state_payload(db, current_user.company_id)


@router.get("/profile", response_model=CompanyProfileResponse)
def get_company_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    return services.serialize_profile(services.get_or_create_profile(db, current_user.company_id))


@router.patch("/profile", response_model=CompanyProfileResponse)
def patch_company_profile(
    payload: CompanyProfilePatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    profile = services.get_or_create_profile(db, current_user.company_id)
    services.apply_field_updates(
        db,
        profile,
        [update.model_dump() for update in payload.updates],
        allow_authoritative_statuses=True,
        final_approved=payload.final_approved,
    )
    return services.serialize_profile(profile)


@router.get("/session", response_model=SessionResponse)
def get_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    profile = services.get_or_create_profile(db, current_user.company_id)
    completion = services.refresh_completion(profile)
    if session.is_completed != completion["can_complete"]:
        session.is_completed = completion["can_complete"]
        db.commit()
    return {"is_completed": session.is_completed}


@router.get("/chat", response_model=list[ChatMessageResponse])
def get_chat_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    messages = (
        db.query(OnboardingMessage)
        .options(joinedload(OnboardingMessage.attachments))
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
    return [_message_payload(message) for message in messages]


@router.get("/chat/state", response_model=OnboardingStateResponse)
def get_chat_state(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    return _state_payload(db, current_user.company_id)


@router.post("/chat/bootstrap", response_model=ChatTurnResponse, status_code=202)
async def bootstrap_chat(
    payload: ChatBootstrapRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    existing = (
        db.query(OnboardingMessage)
        .options(joinedload(OnboardingMessage.attachments))
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.desc())
        .first()
    )
    if existing:
        if existing.sender != SenderType.AI:
            raise HTTPException(status_code=409, detail="The initial message is still being processed.")
        profile = services.get_or_create_profile(db, current_user.company_id)
        previous_user = (
            db.query(OnboardingMessage)
            .options(joinedload(OnboardingMessage.attachments))
            .filter(
                OnboardingMessage.session_id == session.id,
                OnboardingMessage.sender == SenderType.USER,
                OnboardingMessage.created_at <= existing.created_at,
            )
            .order_by(OnboardingMessage.created_at.desc())
            .first()
        )
        sources = (
            db.query(CompanyOnboardingSource)
            .filter(CompanyOnboardingSource.message_id == previous_user.id)
            .all()
        ) if previous_user else []
        return {
            "message": _message_payload(existing), "profile": services.serialize_profile(profile),
            "user_message": _message_payload(previous_user) if previous_user else None,
            "accepted_fields": [], "rejected_updates": [],
            "sources": [source_service.serialize_source(source) for source in sources],
            "next_question": _next_question(profile),
        }
    if payload.initial_url and not payload.skip_website:
        profile = services.get_or_create_profile(db, current_user.company_id)
        url = str(payload.initial_url)
        try:
            user_message = services.save_message(
                db, session.id, SenderType.USER, url, commit=False,
            )
            source = source_service.create_url_source(
                db, company_id=current_user.company_id, user_id=current_user.id,
                url=url, message_id=user_message.id, commit=False,
            )
            job = job_service.enqueue(
                db, scope="company", company_id=current_user.company_id,
                source_id=source.id, url=url, session_id=session.id,
                message_id=user_message.id, commit=False,
            )
            source = job_service.deduplicate_source(db, job, source, commit=False)
            status_message = services.save_message(
                db, session.id, SenderType.AI,
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
            "message": _message_payload(status_message), "user_message": _message_payload(user_message),
            "profile": services.serialize_profile(profile), "accepted_fields": [], "rejected_updates": [],
            "sources": [source_service.serialize_source(source)], "next_question": _next_question(profile),
        }
    return start_chat(db, current_user)


@router.post("/chat/start", response_model=ChatTurnResponse)
def start_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    profile = services.get_or_create_profile(db, current_user.company_id)
    existing = (
        db.query(OnboardingMessage)
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.desc())
        .first()
    )
    if existing:
        if existing.sender != SenderType.AI:
            raise HTTPException(status_code=409, detail="The conversation has already started.")
        message = existing
    else:
        first_name = (current_user.first_name or "there").strip()
        company = db.query(Company).filter(Company.id == current_user.company_id).first()
        registered_name = company.name if company else None
        existing_name = (profile.profile_data or {}).get("official_company_name") or registered_name
        if existing_name:
            intro = (
                f"Welcome, **{first_name}**. I found **{existing_name}** in your account details. "
                "I can use it as the official company name, or you can correct it.\n\n"
                "Would you like me to use this name? You can also paste a company website or social profile, "
                "or attach supporting documents, and I'll prepare the relevant details for your review."
            )
        else:
            intro = (
                f"Welcome, **{first_name}**. I'll help you build a reliable Company Profile without making "
                "you complete a long form.\n\nWhat is the **official company name**? You can also paste a website "
                "or social profile, or attach one or more supporting documents."
            )
        message = services.save_message(db, session.id, SenderType.AI, intro, ui_payload=_next_question(profile))
    return {
        "message": _message_payload(message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [],
        "rejected_updates": [],
        "sources": [],
        "next_question": _next_question(profile),
    }


@router.post("/chat", response_model=ChatTurnResponse)
async def send_chat_message(
    payload: ChatMessagePayload,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    request_id = f"req_{uuid.uuid4().hex}"
    response.headers["X-Request-ID"] = request_id
    session = services.get_or_create_session(db, current_user.company_id)
    profile = services.get_or_create_profile(db, current_user.company_id)
    db.query(OnboardingSession).filter(OnboardingSession.id == session.id).with_for_update().one()
    active_question = services.get_active_question(
        db, session.id, payload.in_reply_to_message_id,
    )
    resolved_question_id = active_question.id if active_question else payload.in_reply_to_message_id
    user_message = services.save_message(
        db, session.id, SenderType.USER, payload.message,
        in_reply_to_message_id=resolved_question_id,
        commit=False,
    )

    resolution = services.resolve_answer_to_question(
        db,
        session_id=session.id,
        message_id=resolved_question_id,
        answer=payload.message,
        profile=profile,
    )
    if not resolution.handled:
        fallback_updates = services.deterministic_context_update(payload.message, profile)
        if fallback_updates:
            resolution = services.QuestionResolution(True, "accepted", fallback_updates)

    if resolution.action == "approve_profile":
        if not _is_authorized_admin(current_user):
            db.rollback()
            raise HTTPException(
                status_code=403,
                detail="Only a Company administrator or assistant can approve the Company Profile.",
            )
        try:
            completion = services.approve_profile(db, profile, commit=False)
        except ValueError:
            resolution = services.QuestionResolution(
                True,
                "rejected",
                [],
                "profile_has_blockers",
                resolution.question,
            )
        else:
            session.is_completed = completion["can_complete"]
            db.add(session)
            services.record_message_response(
                db,
                session.id,
                resolved_question_id,
                payload.message,
                status="accepted",
                commit=False,
            )
            ai_message = services.save_message(
                db,
                session.id,
                SenderType.AI,
                (
                    "Your **Company Profile has been approved successfully**. "
                    "You can now continue to Project Onboarding."
                ),
                ui_payload=None,
                in_reply_to_message_id=user_message.id,
                commit=False,
            )
            db.commit()
            db.refresh(user_message)
            db.refresh(ai_message)
            db.refresh(profile)
            return {
                "request_id": request_id,
                "message_saved": True,
                "profile_changed": True,
                "field_update_status": "accepted",
                "assistant_status": "deterministic",
                "source_actions": [],
                "message": _message_payload(ai_message),
                "user_message": _message_payload(user_message),
                "profile": services.serialize_profile(profile),
                "accepted_fields": [],
                "rejected_updates": [],
                "sources": [],
                "next_question": _next_question(profile),
            }

    deterministic_result = None
    if resolution.status == "accepted" and resolution.updates:
        deterministic_result = services.apply_field_updates(
            db,
            profile,
            resolution.updates,
            allow_authoritative_statuses=_is_authorized_admin(current_user),
            commit=False,
        )
        if deterministic_result.accepted:
            services.record_message_response(
                db, session.id, resolved_question_id, payload.message,
                status="accepted",
                commit=False,
            )
        elif deterministic_result.rejected:
            resolution.status = "rejected"
            resolution.reason = deterministic_result.rejected[0].get("reason")

    db.commit()
    db.refresh(user_message)
    if deterministic_result and deterministic_result.accepted:
        db.refresh(profile)

    accepted = deterministic_result.accepted if deterministic_result else []
    rejected = deterministic_result.rejected if deterministic_result else []

    source_results = []
    source_actions: list[dict[str, Any]] = []
    for url in services.extract_urls(payload.message):
        try:
            existing_job = job_service.get_existing_job(
                db, scope="company", company_id=current_user.company_id,
                url=url, session_id=session.id,
            )
            if existing_job:
                source = db.query(CompanyOnboardingSource).filter(
                    CompanyOnboardingSource.id == existing_job.source_id,
                    CompanyOnboardingSource.company_id == current_user.company_id,
                ).first()
                if not source:
                    raise HTTPException(status_code=409, detail="The existing source record is unavailable.")
                action = {
                    "completed": "already_processed",
                    "failed": "already_failed_not_retried",
                    "queued": "already_processing",
                    "processing": "already_processing",
                }.get(existing_job.status, "already_registered")
            else:
                source = source_service.create_url_source(
                    db,
                    company_id=current_user.company_id,
                    user_id=current_user.id,
                    url=url,
                    message_id=user_message.id,
                    propose_official_website=not any(
                        item.get("field") == "official_corporate_website" for item in accepted
                    ),
                    commit=False,
                )
                job_service.enqueue(
                    db, scope="company", company_id=current_user.company_id, source_id=source.id,
                    url=url, session_id=session.id, message_id=user_message.id, commit=False,
                )
                db.commit()
                db.refresh(source)
                action = "queued"
            source_results.append(source)
            source_actions.append({
                "url": url, "action": action, "status": source.status.value,
                "error": source.error_message,
            })
        except HTTPException as exc:
            db.rollback()
            source_actions.append({"url": url, "action": "rejected", "status": "failed", "error": exc.detail})
        except Exception:
            db.rollback()
            source_actions.append({"url": url, "action": "failed_to_queue", "status": "failed", "error": "The source could not be queued."})

    active_source = any(item["action"] in {"queued", "already_processing"} for item in source_actions)
    stage = _runtime_workflow_stage(
        db, current_user.company_id, profile, processing=active_source,
    )
    next_question = _stage_next_question(stage, profile)
    continuation = _stage_continuation(stage, profile)

    if resolution.handled or source_actions:
        if accepted:
            assistant_text = _accepted_response(
                current_user.first_name, accepted, profile, continuation=continuation,
            )
        elif resolution.status == "rejected":
            explanations = {
                "invalid_question": "That question is no longer available.",
                "stale_question": "That question is no longer the active step.",
                "empty_answer": "Please enter a value before continuing.",
                "invalid_url": "Please enter a valid public website URL or choose No website.",
                "url_not_valid_for_field": "A URL cannot be saved as the value for this field.",
                "minimum_words": "Please provide a more complete answer.",
                "minimum_characters": "Please provide a more complete answer.",
                "missing_reference_value": "The referenced profile value is not available. Please enter the value directly.",
                "profile_has_blockers": "The profile changed before approval and still has required information pending.",
            }
            assistant_text = explanations.get(resolution.reason or "", "I couldn't safely apply that answer.")
            assistant_text += " " + _next_prompt(profile)
        else:
            assistant_text = _next_prompt(profile)

        failed_existing = [item for item in source_actions if item["action"] == "already_failed_not_retried"]
        if failed_existing:
            assistant_text = (
                "This website is already registered and its previous automated analysis failed. "
                "I did not retry it automatically; use **Retry processing** if you want another attempt.\n\n"
                + assistant_text
            )
        elif active_source:
            assistant_text = (
                (assistant_text + "\n\n" if accepted else "")
                + "I'm processing the new source now. The result will appear automatically."
            )

        ai_message = services.save_message(
            db, session.id, SenderType.AI, assistant_text,
            ui_payload=next_question,
            in_reply_to_message_id=user_message.id,
        )
        return {
            "request_id": request_id,
            "message_saved": True,
            "profile_changed": bool(accepted),
            "field_update_status": resolution.status,
            "assistant_status": "deterministic",
            "source_actions": source_actions,
            "message": _message_payload(ai_message),
            "user_message": _message_payload(user_message),
            "profile": services.serialize_profile(profile),
            "accepted_fields": [item["field"] for item in accepted],
            "rejected_updates": _rejected_payload(rejected),
            "sources": [source_service.serialize_source(source) for source in source_results],
            "next_question": next_question,
        }

    ai_config = get_ai_config(db, current_user.company_id)

    agent_config = ai_config.agent_onboarding_empresa or {}
    system_instruction = _system_instruction(agent_config)
    history = (
        db.query(OnboardingMessage)
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
    company = db.query(Company).filter(Company.id == current_user.company_id).first()
    messages_history = [
        {"role": "system", "content": system_instruction},
        {
            "role": "system",
            "content": "RUNTIME CONTEXT:\n" + json.dumps(
                {
                    "current_user": {
                        "first_name": current_user.first_name,
                        "role": current_user.role.value,
                    },
                    "registered_company_name": company.name if company else None,
                    "profile": services.serialize_profile(profile),
                    "new_sources": [source_service.serialize_source(source) for source in source_results],
                    "source_errors": [],
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    for history_message in history[-12:]:
        messages_history.append(
            {
                "role": "user" if history_message.sender == SenderType.USER else "assistant",
                "content": history_message.content,
            }
        )

    model = agent_config.get("model", "openai/gpt-4o-mini")
    assistant_status = "llm"
    try:
        if not ai_config.openrouter_api_key:
            raise ValueError("AI configuration is incomplete")
        raw = await generate_llm_response(
            ai_config.openrouter_api_key,
            model,
            messages_history,
            response_format={"type": "json_object"},
            temperature=0.25,
            raise_on_error=True,
        )
        parsed = _parse_agent_response(raw)
        if parsed is None:
            repair_messages = messages_history + [
                {"role": "assistant", "content": raw},
                {
                    "role": "system",
                    "content": "Repair the preceding response. Return only a valid JSON object matching the contract.",
                },
            ]
            repaired = await generate_llm_response(
                ai_config.openrouter_api_key,
                model,
                repair_messages,
                response_format={"type": "json_object"},
                temperature=0,
                raise_on_error=True,
            )
            parsed = _parse_agent_response(repaired)
    except (httpx.HTTPError, ValueError) as exc:
        parsed = None
        assistant_status = "fallback"

    if parsed is None:
        assistant_text, updates, final_approved = (
            "I saved your message, but the assistant is temporarily unavailable. " + _next_prompt(profile),
            [],
            None,
        )
    else:
        assistant_text, updates, final_approved = parsed

    already_applied = {item["field"] for item in deterministic_result.accepted} if deterministic_result else set()
    updates = [item for item in updates if services.normalize_field_key(item.get("field")) not in already_applied]
    result = services.apply_field_updates(
        db,
        profile,
        updates,
        allow_authoritative_statuses=_is_authorized_admin(current_user),
        # Final approval is a server-owned command resolved above. A model
        # response can propose field updates but cannot complete onboarding.
        final_approved=None,
    )
    accepted = (deterministic_result.accepted if deterministic_result else []) + result.accepted
    rejected = (deterministic_result.rejected if deterministic_result else []) + result.rejected

    if accepted:
        stage = _runtime_workflow_stage(db, current_user.company_id, profile)
        next_question = _stage_next_question(stage, profile)
        assistant_text = _accepted_response(
            current_user.first_name,
            accepted,
            profile,
            continuation=_stage_continuation(stage, profile),
        )
        services.record_message_response(
            db, session.id, payload.in_reply_to_message_id, payload.message,
            status="accepted",
        )
    elif rejected:
        stage = _runtime_workflow_stage(db, current_user.company_id, profile)
        next_question = _stage_next_question(stage, profile)
        assistant_text = (
            "I understood your response, but I couldn't safely apply it to the profile. "
            "Nothing was changed. " + _stage_continuation(stage, profile)
        )
    else:
        stage = _runtime_workflow_stage(db, current_user.company_id, profile)
        next_question = _stage_next_question(stage, profile)
    db.query(OnboardingSession).filter(OnboardingSession.id == session.id).with_for_update().one()
    ai_message = db.query(OnboardingMessage).filter(
        OnboardingMessage.session_id == session.id,
        OnboardingMessage.sender == SenderType.AI,
        OnboardingMessage.in_reply_to_message_id == user_message.id,
    ).order_by(OnboardingMessage.created_at.desc()).first()
    if not ai_message:
        ai_message = services.save_message(
            db, session.id, SenderType.AI, assistant_text,
            ui_payload=next_question,
            in_reply_to_message_id=user_message.id,
        )
    return {
        "request_id": request_id,
        "message_saved": True,
        "profile_changed": bool(accepted),
        "field_update_status": "accepted" if accepted else ("rejected" if rejected else "not_applicable"),
        "assistant_status": assistant_status,
        "source_actions": source_actions,
        "message": _message_payload(ai_message),
        "user_message": _message_payload(user_message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [item["field"] for item in accepted],
        "rejected_updates": _rejected_payload(rejected),
        "sources": [source_service.serialize_source(source) for source in source_results],
        "next_question": next_question,
    }


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    sources = (
        db.query(CompanyOnboardingSource)
        .filter(CompanyOnboardingSource.company_id == current_user.company_id)
        .order_by(CompanyOnboardingSource.created_at.desc())
        .all()
    )
    return [source_service.serialize_source(source) for source in sources]


@router.get("/sources/{source_id}/file")
def download_source_file(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    source = db.query(CompanyOnboardingSource).filter(
        CompanyOnboardingSource.id == source_id,
        CompanyOnboardingSource.company_id == current_user.company_id,
        CompanyOnboardingSource.storage_path.isnot(None),
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="File not found.")
    try: path = storage_service.resolve_company_file(source.storage_path)
    except ValueError as exc: raise HTTPException(status_code=404, detail="File not found.") from exc
    if not path.is_file(): raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        path, media_type=source.mime_type or "application/octet-stream",
        filename=source.original_filename or source.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/sources/{source_id}/retry", response_model=SourceResponse, status_code=202)
def retry_url_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    source = db.query(CompanyOnboardingSource).filter(
        CompanyOnboardingSource.id == source_id,
        CompanyOnboardingSource.company_id == current_user.company_id,
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    if not source.url:
        raise HTTPException(status_code=409, detail="This source has no URL to retry.")
    if not job_service.retry_job(db, scope="company", source_id=source.id):
        raise HTTPException(status_code=409, detail="This source has no recoverable job.")
    source.status = source.status.__class__.PROCESSING
    source.error_message = None
    db.add(source)
    db.commit()
    db.refresh(source)
    return source_service.serialize_source(source)


@router.post("/sources/url", response_model=SourceResponse, status_code=202)
async def add_url_source(
    payload: ScrapeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    try:
        source = source_service.create_url_source(
            db,
            company_id=current_user.company_id,
            user_id=current_user.id,
            url=str(payload.url),
            commit=False,
        )
        job = job_service.enqueue(
            db, scope="company", company_id=current_user.company_id, source_id=source.id,
            url=str(payload.url), session_id=session.id, commit=False,
        )
        source = job_service.deduplicate_source(db, job, source, commit=False)
        db.commit()
        db.refresh(source)
    except Exception:
        db.rollback()
        raise
    return source_service.serialize_source(source)


@router.post("/sources/files", response_model=list[SourceResponse])
async def add_file_sources(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    session = services.get_or_create_session(db, current_user.company_id)
    user_message = services.save_message(
        db, session.id, SenderType.USER,
        f"Attached {len(files)} company file{'s' if len(files) != 1 else ''}.",
    )
    sources = []
    for upload in files:
        sources.append(
            await source_service.ingest_file(
                db,
                company_id=current_user.company_id,
                user_id=current_user.id,
                upload=upload,
                message_id=user_message.id,
            )
        )
    finalize_source_group(
        db,
        scope="company",
        company_id=current_user.company_id,
        message_id=user_message.id,
    )
    db.commit()
    return [source_service.serialize_source(source) for source in sources]


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalDecisionResponse)
def decide_proposal(
    proposal_id: str,
    payload: ProposalDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    proposal = db.query(CompanyOnboardingProposal).filter(CompanyOnboardingProposal.id == proposal_id).first()
    if not proposal or proposal.source.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    proposal, profile = source_service.review_proposal(
        db,
        proposal=proposal,
        company_id=current_user.company_id,
        user_id=current_user.id,
        action=payload.action,
        corrected_value=payload.value,
    )
    _continue_after_source_review(db, proposal=proposal, profile=profile)
    db.commit()
    db.refresh(proposal)
    return {
        "proposal": source_service.serialize_proposal(proposal),
        "profile": services.serialize_profile(profile),
    }


@router.post("/scrape-website", response_model=SourceResponse, deprecated=True)
async def trigger_scrape(
    payload: ScrapeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    source = await source_service.ingest_url(
        db,
        company_id=current_user.company_id,
        user_id=current_user.id,
        url=str(payload.url),
    )
    return source_service.serialize_source(source)


def _system_instruction(agent_config: dict[str, Any]) -> str:
    field_catalog = [{"key": key, "label": value.label} for key, value in FIELD_BY_KEY.items()]
    return (
        f"{agent_config.get('system_prompt', '')}\n\n"
        f"FLOW PROTOCOL:\n{agent_config.get('protocol_prompt', '')}\n\n"
        f"GUARDRAILS:\n{agent_config.get('guardrails_prompt', '')}\n\n"
        "APPLICATION OUTPUT CONTRACT: Return only one valid JSON object with assistant_message, "
        "verified_updates, and final_approved. assistant_message is concise user-facing Markdown. "
        "verified_updates is an array; every field must use a canonical key from FIELD CATALOG. "
        "Never expose JSON, canonical keys, statuses, confidence, or source metadata in assistant_message. "
        "Do not say information was saved; acknowledge it neutrally because the application validates writes "
        "after your response. Ask one focused question based on the first unresolved blocker.\n"
        f"FIELD CATALOG: {json.dumps(field_catalog)}"
    )
