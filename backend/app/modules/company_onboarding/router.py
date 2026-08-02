from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.companies.models import Company
from app.modules.users.models import User, UserRole

from . import services, source_service
from .completion import FIELD_BY_KEY
from .models import CompanyOnboardingProposal, CompanyOnboardingSource, OnboardingMessage, SenderType
from .schemas import (
    ChatMessagePayload,
    ChatMessageResponse,
    ChatTurnResponse,
    CompanyProfilePatch,
    CompanyProfileResponse,
    ProposalDecision,
    ProposalDecisionResponse,
    ScrapeRequest,
    SessionResponse,
    SourceResponse,
)


router = APIRouter()
ALLOWED_ROLES = [UserRole.ADMIN, UserRole.MKT]
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def _is_authorized_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


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
    return {"sender": "ai", "content": message.content, "created_at": message.created_at}


def _next_prompt(profile) -> str:
    completion = services.serialize_profile(profile)["completion"]
    if not completion["blockers"]:
        return "Please review the profile summary and confirm whether it is ready for final approval."
    label = completion["blockers"][0]["label"]
    return f"Let's continue with **{label}**. What should I record for this item?"


def _accepted_response(first_name: str | None, accepted: list[dict[str, Any]], profile) -> str:
    greeting = f"Thanks, {first_name}." if first_name else "Thanks."
    lines = []
    for item in accepted:
        label = FIELD_BY_KEY[item["field"]].label
        value = item.get("value")
        if isinstance(value, dict) and value.get("exists") is False:
            display = "No official website"
        elif isinstance(value, (dict, list)):
            display = json.dumps(value, ensure_ascii=False)
        else:
            display = str(value)
        lines.append(f"- **{label}:** {display}")
    return f"{greeting} I updated the profile with:\n\n" + "\n".join(lines) + "\n\n" + _next_prompt(profile)


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
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
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
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
    return [
        {
            "sender": "user" if message.sender == SenderType.USER else "ai",
            "content": message.content,
            "created_at": message.created_at,
        }
        for message in messages
    ]


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
        message = services.save_message(db, session.id, SenderType.AI, intro)
    return {
        "message": _message_payload(message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [],
        "rejected_updates": [],
        "sources": [],
    }


@router.post("/chat", response_model=ChatTurnResponse)
async def send_chat_message(
    payload: ChatMessagePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    session = services.get_or_create_session(db, current_user.company_id)
    profile = services.get_or_create_profile(db, current_user.company_id)
    ai_config = get_ai_config(db, current_user.company_id)
    if not ai_config.openrouter_api_key:
        raise HTTPException(status_code=500, detail="AI configuration is incomplete.")

    services.save_message(db, session.id, SenderType.USER, payload.message)
    deterministic = services.deterministic_context_update(payload.message, profile)
    deterministic_result = services.apply_field_updates(
        db,
        profile,
        deterministic,
        allow_authoritative_statuses=_is_authorized_admin(current_user),
    ) if deterministic else None

    source_results = []
    source_errors = []
    for raw_url in URL_PATTERN.findall(payload.message)[:3]:
        url = raw_url.rstrip(".,;:!?)\"]}")
        try:
            source_results.append(
                await source_service.ingest_url(
                    db,
                    company_id=current_user.company_id,
                    user_id=current_user.id,
                    url=url,
                )
            )
        except HTTPException as exc:
            source_errors.append({"url": url, "error": exc.detail})

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
                    "source_errors": source_errors,
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
    try:
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
        raise HTTPException(status_code=502, detail="The onboarding assistant is temporarily unavailable.") from exc

    if parsed is None:
        assistant_text, updates, final_approved = (
            "I couldn't validate my internal response, so I left your profile unchanged. " + _next_prompt(profile),
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
    elif rejected:
        assistant_text = (
            "I understood your response, but I couldn't safely apply it to the profile. "
            "Nothing was changed. " + _next_prompt(profile)
        )
    ai_message = services.save_message(db, session.id, SenderType.AI, assistant_text)
    return {
        "message": _message_payload(ai_message),
        "profile": services.serialize_profile(profile),
        "accepted_fields": [item["field"] for item in accepted],
        "rejected_updates": _rejected_payload(rejected),
        "sources": [source_service.serialize_source(source) for source in source_results],
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


@router.post("/sources/url", response_model=SourceResponse)
async def add_url_source(
    payload: ScrapeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    source = await source_service.ingest_url(
        db,
        company_id=current_user.company_id,
        user_id=current_user.id,
        url=str(payload.url),
    )
    return source_service.serialize_source(source)


@router.post("/sources/files", response_model=list[SourceResponse])
async def add_file_sources(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    if not files or len(files) > source_service.MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {source_service.MAX_FILES} files.")
    sources = []
    for upload in files:
        sources.append(
            await source_service.ingest_file(
                db,
                company_id=current_user.company_id,
                user_id=current_user.id,
                upload=upload,
            )
        )
    return [source_service.serialize_source(source) for source in sources]


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalDecisionResponse)
def decide_proposal(
    proposal_id: str,
    payload: ProposalDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
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
    return {
        "proposal": source_service.serialize_proposal(proposal),
        "profile": services.serialize_profile(profile),
    }


@router.post("/scrape-website", response_model=SourceResponse, deprecated=True)
async def trigger_scrape(
    payload: ScrapeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
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
