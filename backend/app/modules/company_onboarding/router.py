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
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole

from . import services, source_service, storage_service
from .completion import FIELD_BY_KEY
from .models import (
    CompanyOnboardingProposal,
    CompanyOnboardingSource,
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
    OnboardingStateResponse,
    ProposalDecision,
    ProposalDecisionResponse,
    ScrapeRequest,
    SessionResponse,
    SourceResponse,
)


router = APIRouter()
ALLOWED_ROLES = [*TENANT_MANAGER_ROLES, UserRole.MKT]


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
    return {
        "id": message.id,
        "sender": "user" if message.sender == SenderType.USER else "ai",
        "content": message.content,
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
    blockers = services.serialize_profile(profile)["completion"]["blockers"]
    return build_next_question(
        blockers,
        final_prompt="Review the Company Profile and choose whether to approve it or make changes.",
    )


def _accepted_response(first_name: str | None, accepted: list[dict[str, Any]], profile) -> str:
    greeting = f"Thanks, {first_name}." if first_name else "Thanks."
    lines = []
    for item in accepted:
        label = FIELD_BY_KEY[item["field"]].label
        value = item.get("value")
        if isinstance(value, dict) and value.get("exists") is False:
            display = "No official website"
        elif isinstance(value, dict) and value.get("url"):
            display = value["url"]
        elif isinstance(value, (dict, list)):
            display = json.dumps(value, ensure_ascii=False)
        else:
            display = str(value)
        lines.append(f"- **{label}:** {display}")
    return f"{greeting} I updated the profile with:\n\n" + "\n".join(lines) + "\n\n" + _next_prompt(profile)


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
    elif not messages and not sources:
        stage = "website"
    else:
        stage = "conversation"
    timestamps = [profile.updated_at, *[item.created_at for item in messages], *[item.updated_at for item in sources]]
    version = int(max((item.timestamp() for item in timestamps if item), default=0) * 1000)
    return {
        "messages": [_message_payload(message) for message in messages],
        "profile": serialized_profile,
        "sources": [source_service.serialize_source(source) for source in sources],
        "next_question": _next_question(profile),
        "stage": stage,
        "version": version,
    }


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
    user_message = services.save_message(
        db, session.id, SenderType.USER, payload.message,
        in_reply_to_message_id=payload.in_reply_to_message_id,
    )

    resolution = services.resolve_answer_to_question(
        db,
        session_id=session.id,
        message_id=payload.in_reply_to_message_id,
        answer=payload.message,
        profile=profile,
    )
    if not resolution.handled:
        fallback_updates = services.deterministic_context_update(payload.message, profile)
        if fallback_updates:
            resolution = services.QuestionResolution(True, "accepted", fallback_updates)

    deterministic_result = None
    if resolution.status == "accepted" and resolution.updates:
        deterministic_result = services.apply_field_updates(
            db,
            profile,
            resolution.updates,
            allow_authoritative_statuses=_is_authorized_admin(current_user),
        )
        if deterministic_result.accepted:
            services.record_message_response(
                db, session.id, payload.in_reply_to_message_id, payload.message,
                status="accepted",
            )

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

    accepted = deterministic_result.accepted if deterministic_result else []
    rejected = deterministic_result.rejected if deterministic_result else []
    active_source = any(item["action"] in {"queued", "already_processing"} for item in source_actions)

    if resolution.handled or source_actions:
        if accepted:
            assistant_text = _accepted_response(current_user.first_name, accepted, profile)
        elif resolution.status == "rejected":
            explanations = {
                "invalid_question": "That question is no longer available.",
                "stale_question": "That question is no longer the active step.",
                "empty_answer": "Please enter a value before continuing.",
                "invalid_url": "Please enter a valid public website URL or choose No website.",
                "url_not_valid_for_field": "A URL cannot be saved as the value for this field.",
                "answer_too_short": "Please provide a more complete answer.",
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
                (assistant_text.rsplit("\n\n", 1)[0] + "\n\n" if accepted else "")
                + "I'm processing the new source now. The result will appear automatically."
            )

        ai_message = services.save_message(
            db, session.id, SenderType.AI, assistant_text,
            ui_payload=None if active_source else _next_question(profile),
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
            "next_question": _next_question(profile),
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
        final_approved=final_approved,
    )
    accepted = (deterministic_result.accepted if deterministic_result else []) + result.accepted
    rejected = (deterministic_result.rejected if deterministic_result else []) + result.rejected

    if accepted:
        assistant_text = _accepted_response(current_user.first_name, accepted, profile)
        services.record_message_response(
            db, session.id, payload.in_reply_to_message_id, payload.message,
            status="accepted",
        )
    elif rejected:
        assistant_text = (
            "I understood your response, but I couldn't safely apply it to the profile. "
            "Nothing was changed. " + _next_prompt(profile)
        )
    db.query(OnboardingSession).filter(OnboardingSession.id == session.id).with_for_update().one()
    ai_message = db.query(OnboardingMessage).filter(
        OnboardingMessage.session_id == session.id,
        OnboardingMessage.sender == SenderType.AI,
        OnboardingMessage.in_reply_to_message_id == user_message.id,
    ).order_by(OnboardingMessage.created_at.desc()).first()
    if not ai_message:
        ai_message = services.save_message(
            db, session.id, SenderType.AI, assistant_text,
            ui_payload=_next_question(profile),
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
        "next_question": _next_question(profile),
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
