"""Published onboarding snapshots and append-only audit, in the caller's transaction.

Profile columns remain the editable draft. Nothing here commits, deletes chat
history, approves a source, or publishes an LLM's proposed final_approved flag.
"""
from copy import deepcopy

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect


def _persisted(profile):
    state = inspect(profile, raiseerr=False)
    return bool(state is not None and getattr(state, "persistent", False))


def snapshot(profile, db=None) -> dict:
    value = {
        "profile_id": getattr(profile, "id", None),
        "data": deepcopy(getattr(profile, "profile_data", None) or {}),
        "states": deepcopy(profile.field_states or {}),
        "sources": deepcopy(getattr(profile, "field_sources", None) or {}),
    }
    project = getattr(profile, "project", None)
    value["company_id"] = getattr(project, "company_id", None) if project else getattr(profile, "company_id", None)
    if project is not None and db is not None:
        from app.modules.projects.models import ProjectPropertyType, ProjectUnit
        value["project_id"] = project.id
        value["project_name"] = project.name
        with db.no_autoflush:
            for key, model in (("property_types", ProjectPropertyType), ("units", ProjectUnit)):
                rows = db.query(model).filter(model.project_id == project.id).order_by(model.created_at, model.id).all()
                if key == "property_types":
                    rows = sorted((r for r in rows if r.review_status == "confirmed"), key=lambda r: (r.sort_order, r.created_at, r.id))
                value[key] = [{col.name: getattr(row, col.name) for col in model.__table__.columns} for row in rows]
    return jsonable_encoder(value)


def published_snapshot(profile) -> dict | None:
    value = getattr(profile, "published_snapshot", None)
    if not isinstance(value, dict) or value.get("profile_id") != profile.id:
        return None
    project = getattr(profile, "project", None)
    company_id = project.company_id if project else getattr(profile, "company_id", None)
    if value.get("company_id") != company_id or not isinstance(value.get("states"), dict):
        return None
    return value


def active_approved(profile) -> bool:
    return bool(profile and (getattr(profile, "final_approved", False) or published_snapshot(profile)))


def lock_for_approval(db, profile):
    """Approve the latest draft under the same lock used by editing cards."""
    if _persisted(profile):
        # Flush this transaction's explicit field updates before reloading. A
        # simultaneous editor must finish before we validate and publish.
        db.flush()
        db.query(type(profile)).filter(type(profile).id == profile.id).with_for_update().one()
        db.refresh(profile)


def require_capability(profile, capability="manual_messaging"):
    """Do not convert an explicit deferred/rejected permission into activation.

    Old profiles without the operational fields retain their pre-existing final
    approval. No missing field is backfilled with an invented consent.
    """
    from app.modules.onboarding_contract import field_approved
    approved = published_snapshot(profile)
    states = approved["states"] if approved else profile.field_states or {}
    data = approved["data"] if approved else profile.profile_data or {}
    required = {"manual_messaging": ["sales_authorization"],
                "appointments": ["sales_authorization", "sales_contacts", "appointment_routing"],
                "meta_lead_ads": ["sales_authorization", "campaigns_defined", "meta_connection_verified"]}[capability]
    blocked = [key for key in required if key in states and not field_approved(states[key])]
    # Explicit withdrawal of AI sales permission is immediate, even while the
    # rest of an approved profile's new revision is pending.
    if data.get("sales_authorization") is False or (profile.profile_data or {}).get("sales_authorization") is False:
        blocked.append("sales_authorization")
    if blocked:
        raise HTTPException(status_code=409, detail={
            "message": "This capability still needs explicit approval or setup.",
            "capability": capability, "blockers": sorted(set(blocked)),
        })


def begin_edit(db, profile, *, expected_revision=None) -> dict:
    if not _persisted(profile):
        return snapshot(profile)
    # Serialize writes to different cards of the same profile, including catalog
    # changes. Session row locks elsewhere alone do not cover PATCH requests.
    db.query(type(profile)).filter(type(profile).id == profile.id).with_for_update().one()
    db.refresh(profile)
    revision = int(profile.draft_revision or 0)
    if expected_revision is not None and expected_revision != revision:
        raise HTTPException(status_code=409, detail={
            "message": "This profile changed in another session. Reload before saving.",
            "code": "onboarding_revision_conflict", "current_revision": revision,
        })
    before = snapshot(profile, db)
    if profile.final_approved and not published_snapshot(profile):
        # Legacy approvals are captured at first edit, not retroactively dated.
        profile.published_snapshot = {**before, "revision": revision, "legacy_capture": True}
    return before


def _audit(db, profile, *, event_type, before, after, actor_user_id=None):
    from app.modules.governance.services import record_platform_event
    from app.modules.users.models import User
    actor = db.query(User).filter(User.id == actor_user_id, User.company_id == after["company_id"]).first() if actor_user_id else None
    record_platform_event(
        db, actor=actor, company_id=after["company_id"],
        event_type=event_type, entity_type="project_profile" if "project_id" in after else "company_profile",
        entity_id=profile.id,
        payload={"revision": profile.draft_revision, "before": before, "after": after},
    )


def record_edit(db, profile, before, *, actor_user_id=None):
    if not _persisted(profile):
        return False
    after = snapshot(profile, db)
    def meaningful(value):
        if isinstance(value, dict):
            return {key: meaningful(item) for key, item in value.items()
                    if key not in {"recorded_at", "created_at", "updated_at", "updated_by_user_id"}}
        if isinstance(value, list):
            return [meaningful(item) for item in value]
        return value
    if meaningful(before) == meaningful(after):
        return False
    profile.draft_revision = int(profile.draft_revision or 0) + 1
    if published_snapshot(profile):
        profile.final_approved = False
        project = getattr(profile, "project", None)
        if project is not None:
            project.onboarding_status = "awaiting_confirmation"
            # Keep original approval identity/date as historical evidence.
    _audit(db, profile, event_type="onboarding.draft_updated", before=before, after=after, actor_user_id=actor_user_id)
    return True


def publish(db, profile, *, actor_user_id=None):
    if not _persisted(profile):
        return
    after = snapshot(profile, db)
    before = published_snapshot(profile)
    if before and all(before.get(key) == value for key, value in after.items()):
        return
    profile.draft_revision = int(profile.draft_revision or 0) + 1
    profile.published_snapshot = {**after, "revision": profile.draft_revision}
    _audit(db, profile, event_type="onboarding.profile_approved", before=before, after=after, actor_user_id=actor_user_id)


def revision_info(profile) -> dict:
    approved = published_snapshot(profile)
    return {
        "draft_revision": int(getattr(profile, "draft_revision", 0) or 0),
        "published_revision": approved.get("revision") if approved else None,
        "active_profile_approved": active_approved(profile),
        "has_pending_changes": bool(approved and not profile.final_approved),
    }
