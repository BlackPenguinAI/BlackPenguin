import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from . import services
from .completion import FIELD_BY_KEY
from .models import OnboardingMessage, SenderType
from .schemas import (
    AgentResponsePayload,
    ChatMessagePayload,
    ChatMessageResponse,
    CompanyProfilePatch,
    CompanyProfileResponse,
    ScrapeRequest,
    SessionResponse,
    FieldUpdate,
)
from .scraper import scrape_and_enrich_profile


router = APIRouter()
ALLOWED_ROLES = [UserRole.ADMIN, UserRole.MKT]
logger = logging.getLogger(__name__)

INVALID_AGENT_RESPONSE = (
    "I couldn't process that response reliably. **Your profile was not changed.** "
    "Please try again or provide the information in a shorter message."
)


def _is_authorized_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def _parse_agent_response(raw: str) -> tuple[str, list[dict[str, Any]], bool | None]:
    clean = raw.strip()
    if clean.startswith("```json") and clean.endswith("```"):
        clean = clean[7:-3].strip()
    try:
        payload = AgentResponsePayload.model_validate(json.loads(clean))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Invalid Company Onboarding agent envelope: %s", exc)
        return INVALID_AGENT_RESPONSE, [], None

    updates: list[dict[str, Any]] = []
    for candidate in payload.verified_updates:
        try:
            updates.append(FieldUpdate.model_validate(candidate).model_dump())
        except ValueError as exc:
            logger.warning("Rejected Company Onboarding agent update: %s", exc)

    return payload.assistant_message, updates, payload.final_approved


def _build_system_instruction(agent_config: dict[str, Any]) -> str:
    canonical_keys = ", ".join(FIELD_BY_KEY)
    return (
        f"{agent_config.get('system_prompt', '')}\n\n"
        f"Protocol:\n{agent_config.get('protocol_prompt', '')}\n\n"
        f"Guardrails:\n{agent_config.get('guardrails_prompt', '')}\n\n"
        "APPLICATION OUTPUT CONTRACT:\n"
        "Return only one valid JSON object; do not use Markdown fences around the JSON. "
        "The object must contain assistant_message, verified_updates, and final_approved. "
        "assistant_message is the only user-facing value and must contain concise, polished "
        "Markdown. verified_updates must be an array of objects with field, value, status, "
        "applicable, source_type, source_reference, and confidence. Never place raw JSON, "
        "canonical keys, statuses, confidence, or source metadata inside assistant_message. "
        "Every verified_updates.field must use one of these exact canonical keys: "
        f"{canonical_keys}. final_approved must be null unless an authorized administrator "
        "explicitly approves the final profile; otherwise it may be true or false."
    )


def _build_messages_history(
    db: Session,
    session_id: str,
    profile: Any,
    system_instruction: str,
    task_instruction: str | None = None,
) -> list[dict[str, str]]:
    messages_history = [{"role": "system", "content": system_instruction}]
    messages_history.append(
        {
            "role": "system",
            "content": "CURRENT PROFILE STATE:\n" + json.dumps(
                {
                    "data": profile.profile_data or {},
                    "fields": profile.field_states or {},
                    "final_approved": profile.final_approved,
                },
                ensure_ascii=False,
            ),
        }
    )
    if task_instruction:
        messages_history.append({"role": "system", "content": task_instruction})

    history = (
        db.query(OnboardingMessage)
        .filter(OnboardingMessage.session_id == session_id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
    for message in history[-10:]:
        messages_history.append(
            {
                "role": "user" if message.sender == SenderType.USER else "assistant",
                "content": message.content,
            }
        )
    return messages_history


@router.get("/profile", response_model=CompanyProfileResponse)
def get_company_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    profile = services.get_or_create_profile(db, current_user.company_id)
    return services.serialize_profile(profile)


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


@router.post("/chat", response_model=ChatMessageResponse)
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
    agent_config = ai_config.agent_onboarding_empresa or {}
    messages_history = _build_messages_history(
        db,
        session.id,
        profile,
        _build_system_instruction(agent_config),
    )

    model = agent_config.get("model", "openai/gpt-4o-mini")
    raw_response = await generate_llm_response(
        ai_config.openrouter_api_key,
        model,
        messages_history,
        response_format={"type": "json_object"},
    )
    assistant_text, updates, final_approved = _parse_agent_response(raw_response)

    if updates or final_approved is not None:
        services.apply_field_updates(
            db,
            profile,
            updates,
            allow_authoritative_statuses=_is_authorized_admin(current_user),
            final_approved=final_approved,
        )

    ai_message = services.save_message(db, session.id, SenderType.AI, assistant_text)
    return {"sender": "ai", "content": ai_message.content, "created_at": ai_message.created_at}


@router.post("/chat/initialize", response_model=ChatMessageResponse)
async def initialize_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(ALLOWED_ROLES)),
):
    """Create the first assistant message without requiring the user to say hello."""
    session = services.get_or_create_session(db, current_user.company_id)
    existing_message = (
        db.query(OnboardingMessage)
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.desc())
        .first()
    )
    if existing_message:
        return {
            "sender": "user" if existing_message.sender == SenderType.USER else "ai",
            "content": existing_message.content,
            "created_at": existing_message.created_at,
        }

    profile = services.get_or_create_profile(db, current_user.company_id)
    ai_config = get_ai_config(db, current_user.company_id)
    if not ai_config.openrouter_api_key:
        raise HTTPException(status_code=500, detail="AI configuration is incomplete.")

    agent_config = ai_config.agent_onboarding_empresa or {}
    messages_history = _build_messages_history(
        db,
        session.id,
        profile,
        _build_system_instruction(agent_config),
        (
            "Start the onboarding now. Welcome the user proactively, summarize only profile "
            "facts that are actually present in CURRENT PROFILE STATE, and ask one focused "
            "question for the highest-priority unresolved required field. Do not display a "
            "list of unavailable fields and do not claim that website or document analysis "
            "occurred unless source data is present."
        ),
    )
    raw_response = await generate_llm_response(
        ai_config.openrouter_api_key,
        agent_config.get("model", "openai/gpt-4o-mini"),
        messages_history,
        response_format={"type": "json_object"},
    )
    assistant_text, _, _ = _parse_agent_response(raw_response)
    ai_message = services.save_message(db, session.id, SenderType.AI, assistant_text)
    return {"sender": "ai", "content": ai_message.content, "created_at": ai_message.created_at}


@router.post("/scrape-website", status_code=202)
def trigger_scrape(
    payload: ScrapeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    background_tasks.add_task(scrape_and_enrich_profile, current_user.company_id, str(payload.url))
    return {"message": "Website analysis started in the background."}
