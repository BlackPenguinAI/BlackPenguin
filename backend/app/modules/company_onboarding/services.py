from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
    "primary administrator": "primary_black_penguin_administrator",
    "primary black penguin administrator": "primary_black_penguin_administrator",
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
    return profile


def get_or_create_session(db: Session, company_id: str) -> OnboardingSession:
    session = db.query(OnboardingSession).filter(OnboardingSession.company_id == company_id).first()
    if not session:
        session = OnboardingSession(company_id=company_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def save_message(db: Session, session_id: str, sender: SenderType, content: str) -> OnboardingMessage:
    message = OnboardingMessage(session_id=session_id, sender=sender, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


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
    db.commit()
    db.refresh(profile)
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

    if next_field == "primary_black_penguin_administrator":
        match = re.fullmatch(
            r"(?:(?:the\s+)?name\s+is\s+)?([a-z][a-z .'-]{1,100})",
            text,
            re.IGNORECASE,
        )
        excluded = {"hi", "hello", "hey", "yes", "no", "ok", "okay"}
        if match and text not in excluded and len(match.group(1).split()) <= 5:
            return [_user_update(next_field, match.group(1).strip().title())]

    return []


def _user_update(field: str, value: Any) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "status": "confirmed",
        "applicable": True,
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
