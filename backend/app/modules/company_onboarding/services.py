from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .completion import (
    FIELD_BY_KEY,
    VALID_STATUSES,
    calculate_completion,
    field_progress,
    normalize_field_key,
)
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

logger = logging.getLogger(__name__)


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
) -> CompanyProfile:
    data = dict(profile.profile_data or {})
    states = dict(profile.field_states or {})
    sources = dict(profile.field_sources or {})

    for update in updates:
        original_field = update.get("field")
        field_key = normalize_field_key(original_field)
        status = update.get("status", "extracted")
        if field_key not in FIELD_BY_KEY or status not in VALID_STATUSES:
            logger.warning(
                "Rejected Company Profile update: field=%r status=%r",
                original_field,
                status,
            )
            continue
        if status in {"confirmed", "corrected_by_user", "not_applicable"} and not allow_authoritative_statuses:
            status = "pending_confirmation"

        value = update.get("value")
        if status != "not_applicable" and value is not None:
            data[field_key] = value

        applicable = update.get("applicable")
        if (
            applicable is None
            and FIELD_BY_KEY[field_key].requirement == "conditionally_required"
            and status != "not_applicable"
            and value is not None
        ):
            applicable = True

        states[field_key] = {
            "status": status,
            "applicable": applicable,
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
    return profile


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
