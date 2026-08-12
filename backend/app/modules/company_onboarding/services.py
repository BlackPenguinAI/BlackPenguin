from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.onboarding_questions import validate_onboarding_value

from .completion import FIELD_BY_KEY, VALID_STATUSES, calculate_completion, field_progress
from .models import CompanyProfile, OnboardingMessage, OnboardingSession, SenderType


LEGACY_FIELD_MAP = {
    "legal_name": "official_company_name",
    "dba": "preferred_display_name",
    "headquarters": "headquarters",
    "year_established": "year_established",
    "asset_classes": "core_asset_classes",
    "market_coverage": "current_operating_footprint",
    "value_proposition": "corporate_value_proposition",
    "key_differentiators": "corporate_differentiators",
    "aum": "assets_under_management",
}

FIELD_ALIASES = {
    "legal name": "official_company_name",
    "company name": "official_company_name",
    "official company name": "official_company_name",
    "display name": "preferred_display_name",
    "preferred display name": "preferred_display_name",
    "official website": "official_corporate_website",
    "corporate website": "official_corporate_website",
    "headquarters": "headquarters",
    "business model": "primary_business_model",
    "asset classes": "core_asset_classes",
    "operating footprint": "current_operating_footprint",
    "short company description": "approved_short_company_description",
    "value proposition": "corporate_value_proposition",
    "differentiators": "corporate_differentiators",
    "dba": "dba",
    "year established": "year_established",
}


@dataclass
class ApplyUpdatesResult:
    profile: CompanyProfile
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]


@dataclass
class QuestionResolution:
    handled: bool
    status: str
    updates: list[dict[str, Any]]
    reason: str | None = None
    question: OnboardingMessage | None = None


DOMAIN_PATTERN = re.compile(
    r"(?<![@\w])(?:https?://)?(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?(?:/[^\s<>]*)?",
    re.IGNORECASE,
)
TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "msclkid"}


def normalize_field_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in FIELD_BY_KEY:
        return candidate
    normalized = re.sub(r"[_\-]+", " ", candidate).strip().lower()
    return FIELD_ALIASES.get(normalized)


def get_or_create_profile(db: Session, company_id: str) -> CompanyProfile:
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).first()
    if not profile:
        profile = CompanyProfile(company_id=company_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    seed_legacy_values(profile)
    if purge_deprecated_profile_fields(profile):
        refresh_completion(profile)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def purge_deprecated_profile_fields(profile: CompanyProfile) -> bool:
    """Remove operational user identity mistakenly stored as Company data."""
    removed = False
    for attribute in ("profile_data", "field_states", "field_sources"):
        values = dict(getattr(profile, attribute, {}) or {})
        if values.pop("primary_black_penguin_administrator", None) is not None:
            setattr(profile, attribute, values)
            flag_modified(profile, attribute)
            removed = True
    return removed


def get_or_create_session(db: Session, company_id: str) -> OnboardingSession:
    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == company_id).first()
    if not session:
        session = OnboardingSession(company_id=company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def save_message(
    db: Session, session_id: str, sender: SenderType, content: str, *,
    ui_payload: dict[str, Any] | None = None,
    in_reply_to_message_id: str | None = None,
    commit: bool = True,
) -> OnboardingMessage:
    if sender == SenderType.AI and isinstance(ui_payload, dict):
        supersede_unanswered_questions(db, session_id)
    message = OnboardingMessage(
        session_id=session_id, sender=sender, content=content,
        ui_payload=ui_payload, in_reply_to_message_id=in_reply_to_message_id,
    )
    db.add(message)
    if commit:
        db.commit()
        db.refresh(message)
    else:
        db.flush()
    return message


def supersede_unanswered_questions(
    db: Session,
    session_id: str,
    *,
    keep_message_id: str | None = None,
) -> bool:
    """Keep a single server-owned active structured question per session."""
    candidates = db.query(OnboardingMessage).filter(
        OnboardingMessage.session_id == session_id,
        OnboardingMessage.sender == SenderType.AI,
        OnboardingMessage.response_payload.is_(None),
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
) -> OnboardingMessage | None:
    """Resolve the current question even when the browser lost its transient reply id."""
    candidates = [
        message
        for message in db.query(OnboardingMessage).filter(
            OnboardingMessage.session_id == session_id,
            OnboardingMessage.sender == SenderType.AI,
            OnboardingMessage.response_payload.is_(None),
        ).order_by(OnboardingMessage.created_at.desc(), OnboardingMessage.id.desc()).all()
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
    message = db.query(OnboardingMessage).filter(
        OnboardingMessage.id == message_id,
        OnboardingMessage.session_id == session_id,
        OnboardingMessage.sender == SenderType.AI,
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


def normalize_user_url(value: str) -> str | None:
    """Return a safe, stable public URL representation for chat input."""
    candidate = value.strip().rstrip(".,;:!?)\"]}")
    if not candidate:
        return None
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    try:
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower().rstrip(".")
        if not host or "." not in host or " " in host:
            return None
        port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    except ValueError:
        return None
    query = urlencode([
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host + port, path, query, ""))


def extract_urls(message: str) -> list[str]:
    urls: list[str] = []
    for match in DOMAIN_PATTERN.finditer(message):
        normalized = normalize_user_url(match.group(0))
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls[:3]


def resolve_answer_to_question(
    db: Session,
    *,
    session_id: str,
    message_id: str | None,
    answer: str,
    profile: CompanyProfile,
) -> QuestionResolution:
    """Resolve a structured reply using the persisted question, never model inference."""
    if not message_id:
        return QuestionResolution(False, "not_applicable", [])
    question = db.query(OnboardingMessage).filter(
        OnboardingMessage.id == message_id,
        OnboardingMessage.session_id == session_id,
        OnboardingMessage.sender == SenderType.AI,
    ).first()
    if not question or not isinstance(question.ui_payload, dict):
        return QuestionResolution(True, "rejected", [], "invalid_question", question)
    if question.response_payload:
        return QuestionResolution(True, "rejected", [], "stale_question", question)

    unanswered = [item for item in db.query(OnboardingMessage).filter(
        OnboardingMessage.session_id == session_id,
        OnboardingMessage.sender == SenderType.AI,
    ).order_by(OnboardingMessage.created_at.desc(), OnboardingMessage.id.desc()).all()
        if isinstance(item.ui_payload, dict) and not item.response_payload]
    if unanswered and unanswered[0].id != question.id:
        return QuestionResolution(True, "rejected", [], "stale_question", question)

    field = normalize_field_key(question.ui_payload.get("field"))
    if field is None:
        return QuestionResolution(False, "not_applicable", [], question=question)
    text = re.sub(r"\s+", " ", answer).strip()
    if not text:
        return QuestionResolution(True, "rejected", [], "empty_answer", question)

    input_type = str(question.ui_payload.get("input_type") or "text")
    answer_actions = question.ui_payload.get("answer_actions")
    if isinstance(answer_actions, dict):
        action = next(
            (value for label, value in answer_actions.items()
             if str(label).strip().casefold() == text.casefold() and isinstance(value, dict)),
            None,
        )
        if action and action.get("kind") == "not_applicable":
            return QuestionResolution(
                True, "accepted", [_user_update(field, None, status="not_applicable", applicable=False)],
                question=question,
            )
        if action and action.get("kind") == "copy_field":
            source_field = normalize_field_key(action.get("source_field"))
            copied_value = (profile.profile_data or {}).get(source_field) if source_field else None
            if copied_value in (None, "", []):
                return QuestionResolution(True, "rejected", [], "missing_reference_value", question)
            return QuestionResolution(
                True, "accepted", [_user_update(field, copied_value)], question=question,
            )

    urls = extract_urls(text)
    lowered = text.casefold()
    no_website = lowered in {
        "none", "no", "no website", "none exists", "non exists", "no existe",
        "does not exist", "we don't have one", "we do not have one",
    }
    definition = FIELD_BY_KEY[field]
    not_applicable = lowered in {
        "none", "no", "not applicable", "n/a", "no aplica", "does not apply",
        "no dba", "no dba - not applicable", "no dba — not applicable",
        "same as the official company name", "same as legal company name",
    }
    if definition.requirement == "conditionally_required" and not_applicable:
        return QuestionResolution(
            True, "accepted", [_user_update(field, None, status="not_applicable", applicable=False)],
            question=question,
        )
    if field == "official_corporate_website":
        if no_website:
            value: Any = {"exists": False, "url": None}
        elif urls:
            value = {"exists": True, "url": urls[0]}
        else:
            return QuestionResolution(True, "rejected", [], "invalid_url", question)
    elif urls:
        return QuestionResolution(True, "rejected", [], "url_not_valid_for_field", question)
    elif input_type == "multi_select":
        value = [item.strip() for item in re.split(r"[,;]", text) if item.strip()]
        if not value:
            return QuestionResolution(True, "rejected", [], "empty_answer", question)
    else:
        value = text

    validation_error = validate_onboarding_value(field, value)
    if validation_error:
        return QuestionResolution(True, "rejected", [], validation_error["code"], question)
    existing = (profile.profile_data or {}).get(field)
    status = "corrected_by_user" if existing not in (None, "", []) and existing != value else "confirmed"
    return QuestionResolution(True, "accepted", [_user_update(field, value, status=status)], question=question)


def seed_legacy_values(profile: CompanyProfile) -> None:
    data = dict(profile.profile_data or {})
    states = dict(profile.field_states or {})
    changed = False

    for legacy_key, canonical_key in LEGACY_FIELD_MAP.items():
        value = getattr(profile, legacy_key, None)
        if value not in (None, "", []) and canonical_key not in data:
            data[canonical_key] = value
            states[canonical_key] = {
                "status": "pending_confirmation",
                "applicable": None,
            }
            changed = True

    if changed:
        profile.profile_data = data
        profile.field_states = states


def apply_field_updates(
    db: Session,
    profile: CompanyProfile,
    updates: list[dict[str, Any]],
    *,
    allow_authoritative_statuses: bool,
    final_approved: bool | None = None,
    commit: bool = True,
) -> ApplyUpdatesResult:
    data = dict(profile.profile_data or {})
    states = dict(profile.field_states or {})
    sources = dict(profile.field_sources or {})

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw_update in updates:
        update = dict(raw_update)
        field_key = normalize_field_key(update.get("field"))
        status = update.get("status", "extracted")
        if field_key is None:
            rejected.append({"update": raw_update, "reason": "unknown_field"})
            continue
        if status not in VALID_STATUSES:
            rejected.append({"update": raw_update, "reason": "invalid_status"})
            continue
        if status in {"confirmed", "corrected_by_user", "not_applicable"} and not allow_authoritative_statuses:
            status = "pending_confirmation"

        value = update.get("value")
        if status not in {"missing", "not_applicable"} and value in (None, "", []):
            rejected.append({"update": raw_update, "reason": "missing_value"})
            continue
        validation_error = validate_onboarding_value(field_key, value)
        if validation_error:
            rejected.append({"update": raw_update, "reason": validation_error["code"], "validation": validation_error})
            continue
        if status != "not_applicable" and value is not None:
            data[field_key] = value

        states[field_key] = {
            "status": status,
            "applicable": update.get("applicable"),
        }
        if status == "not_applicable":
            states[field_key]["applicable"] = False

        source = {
            key: update.get(key)
            for key in ("source_type", "source_reference", "confidence")
            if update.get(key) is not None
        }
        if source:
            source["recorded_at"] = datetime.utcnow().isoformat()
            sources[field_key] = source

        accepted.append(
            {
                "field": field_key,
                "value": value,
                "status": status,
                "applicable": states[field_key].get("applicable"),
            }
        )

    if final_approved is not None and allow_authoritative_statuses:
        profile.final_approved = final_approved

    profile.profile_data = data
    profile.field_states = states
    profile.field_sources = sources
    flag_modified(profile, "profile_data")
    flag_modified(profile, "field_states")
    flag_modified(profile, "field_sources")
    refresh_completion(profile)

    db.add(profile)
    if commit:
        db.commit()
        db.refresh(profile)
    else:
        db.flush()
    return ApplyUpdatesResult(profile=profile, accepted=accepted, rejected=rejected)


def deterministic_context_update(message: str, profile: CompanyProfile) -> list[dict[str, Any]]:
    """Resolve a few contextual answers that should not depend on LLM formatting."""
    text = re.sub(r"\s+", " ", message.strip()).lower()
    completion = calculate_completion(profile.field_states, final_approved=profile.final_approved)
    next_field = completion["blockers"][0]["field"] if completion["blockers"] else None
    data = profile.profile_data or {}

    if next_field == "preferred_display_name" and text in {
        "same", "same name", "the same", "use the same name", "same as company name",
    }:
        value = data.get("official_company_name")
        if value:
            return [_user_update(next_field, value)]

    no_website_phrases = {
        "none", "no", "no website", "none exists", "non exists", "no existe",
        "does not exist", "we don't have one", "we do not have one",
    }
    compact = re.sub(r"[^a-z]", "", text)
    explicit_no_website = text in no_website_phrases or (
        compact.startswith("no") and ("exist" in compact or "website" in compact)
    )
    if next_field == "official_corporate_website" and explicit_no_website:
        return [_user_update(next_field, {"exists": False, "url": None})]

    if next_field == "headquarters":
        match = re.fullmatch(r"(?:in|at|en)\s+([a-z][a-z .,'-]{1,80})", text, re.IGNORECASE)
        if match:
            return [_user_update(next_field, match.group(1).strip().title())]

    return []


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
        "source_type": "user_input",
        "source_reference": "current user response",
        "confidence": "high",
    }


def refresh_completion(profile: CompanyProfile) -> dict[str, Any]:
    completion = calculate_completion(
        profile.field_states,
        final_approved=profile.final_approved,
    )
    profile.completion_percentage = completion["percentage"]
    profile.is_profile_fully_completed = completion["can_complete"]
    return completion


def serialize_profile(profile: CompanyProfile) -> dict[str, Any]:
    completion = refresh_completion(profile)
    return {
        "id": profile.id,
        "company_id": profile.company_id,
        "data": profile.profile_data or {},
        "fields": field_progress(profile.field_states),
        "completion": completion,
        "updated_at": profile.updated_at,
    }
