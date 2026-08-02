import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.integrations.openrouter_client import generate_llm_response
from app.modules.ai_core.services import get_ai_config
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole

from . import services
from .models import OnboardingMessage, SenderType
from .schemas import (
    ChatMessagePayload,
    ChatMessageResponse,
    CompanyProfilePatch,
    CompanyProfileResponse,
    ScrapeRequest,
    SessionResponse,
)
from .scraper import scrape_and_enrich_profile


router = APIRouter()
ALLOWED_ROLES = [UserRole.ADMIN, UserRole.MKT]


def _is_authorized_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def _parse_agent_response(raw: str) -> tuple[str, list[dict[str, Any]], bool | None]:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return raw, [], None

    if not isinstance(payload, dict):
        return raw, [], None
    assistant_message = payload.get("assistant_message")
    if not isinstance(assistant_message, str):
        return raw, [], None
    updates = payload.get("verified_updates", [])
    if not isinstance(updates, list):
        updates = []
    final_approved = payload.get("final_approved")
    if not isinstance(final_approved, bool):
        final_approved = None
    return assistant_message, updates, final_approved


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
        raise HTTPException(status_code=500, detail="Configuración de IA incompleta.")

    services.save_message(db, session.id, SenderType.USER, payload.message)
    agent_config = ai_config.agent_onboarding_empresa or {}
    system_instruction = (
        f"{agent_config.get('system_prompt', '')}\n\n"
        f"Protocol:\n{agent_config.get('protocol_prompt', '')}\n\n"
        f"Guardrails:\n{agent_config.get('guardrails_prompt', '')}\n\n"
        "APPLICATION OUTPUT CONTRACT: Return only valid JSON. Include "
        "assistant_message (the user-facing text), verified_updates (an array of objects "
        "with field, value, status, applicable, source_type, source_reference and confidence), "
        "and final_approved (boolean only when the administrator explicitly gives final approval). "
        "Do not put the JSON inside markdown fences."
    )

    history = (
        db.query(OnboardingMessage)
        .filter(OnboardingMessage.session_id == session.id)
        .order_by(OnboardingMessage.created_at.asc())
        .all()
    )
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
    for message in history[-10:]:
        messages_history.append(
            {
                "role": "user" if message.sender == SenderType.USER else "assistant",
                "content": message.content,
            }
        )

    model = agent_config.get("model", "openai/gpt-4o-mini")
    raw_response = await generate_llm_response(
        ai_config.openrouter_api_key,
        model,
        messages_history,
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


@router.post("/scrape-website", status_code=202)
def trigger_scrape(
    payload: ScrapeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(RoleChecker([UserRole.ADMIN])),
):
    background_tasks.add_task(scrape_and_enrich_profile, current_user.company_id, str(payload.url))
    return {"message": "El análisis del sitio web comenzó en segundo plano."}
