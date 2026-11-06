"""Persist UI drafts separately from approved facts, without new DB columns."""
from copy import deepcopy
from datetime import datetime
from typing import Literal
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import TENANT_MANAGER_ROLES, User
from app.modules.governance.services import record_platform_event

KEY = "__ui_deferrals__"
router = APIRouter()


def records(profile):
    value = (getattr(profile, "field_sources", None) or {}).get(KEY, {})
    return value if isinstance(value, dict) else {}


def deferred(profile, card):
    return records(profile).get(card, {}).get("deferred") is True


def question_blockers(profile, blockers):
    visible = [item for item in blockers if not deferred(profile, "field:" + item["field"])]
    # A direct Resume action should take the user back to that review, not
    # silently show the first unrelated missing field again.
    resumed = {key: value.get("updated_at", "") for key, value in records(profile).items() if value.get("resumed")}
    return sorted(visible, key=lambda item: resumed.get("field:" + item["field"], ""), reverse=True)


def deferred_question():
    return {"field": None, "label": "Saved for later", "prompt": "Your remaining items are saved for later, not approved. Resume a deferred card to finish the required review.", "input_type": "deferred_review", "options": [], "examples": [], "allow_custom": False, "minimum_words": None}


def resolve_in_sources(sources, card):
    if card not in sources.get(KEY, {}):
        return
    bag = deepcopy(sources[KEY])
    bag[card] = {**bag[card], "deferred": False, "resumed": False, "draft": {}, "completed_at": datetime.utcnow().isoformat()}
    sources[KEY] = bag


def resolve_draft(profile, card):
    if card not in records(profile):
        return
    sources = dict(profile.field_sources or {})
    resolve_in_sources(sources, card)
    profile.field_sources = sources
    flag_modified(profile, "field_sources")


class Decision(BaseModel):
    card: str = Field(min_length=1, max_length=160)
    resume: bool = False
    draft: dict = Field(default_factory=dict)


def save(db, profile, scope, entity_id, payload, actor):
    from app.modules.company_onboarding import models as cm
    from app.modules.company_onboarding.completion import FIELD_BY_KEY as COMPANY_FIELDS
    from app.modules.projects import models as pm
    from app.modules.projects.completion import FIELD_BY_KEY as PROJECT_FIELDS
    company_id = profile.company_id if scope == "company" else profile.project.company_id
    prefix, _, identifier = payload.card.partition(":")
    fields = COMPANY_FIELDS if scope == "company" else PROJECT_FIELDS
    if prefix == "field":
        if identifier not in fields:
            raise HTTPException(422, "Unknown onboarding field.")
    elif prefix == "source":
        model = cm.CompanyOnboardingSource if scope == "company" else pm.ProjectOnboardingSource
        owner = model.company_id if scope == "company" else model.project_id
        if not db.query(model.id).filter(model.id == identifier, owner == entity_id).first():
            raise HTTPException(404, "Source not found in this onboarding.")
    elif prefix == "property" and scope == "project":
        if identifier != "new" and not db.query(pm.ProjectPropertyType.id).filter(pm.ProjectPropertyType.id == identifier, pm.ProjectPropertyType.project_id == entity_id).first():
            raise HTTPException(404, "Property type not found.")
    elif prefix == "material" and scope == "project":
        if not db.query(pm.ProjectSalesAsset.id).filter(pm.ProjectSalesAsset.id == identifier, pm.ProjectSalesAsset.project_id == entity_id).first():
            raise HTTPException(404, "Sales material not found in this onboarding.")
    elif payload.card not in {"team", "enrichment", "catalog", "materials", "documents", "meta_setup", "final_approval"}:
        raise HTTPException(422, "Unknown onboarding card.")
    if len(json.dumps(payload.draft).encode()) > 200000:
        raise HTTPException(413, "This draft is too large. Upload the document before configuring it later.")
    def has_credentials(value):
        if isinstance(value, dict):
            return any(re.search(r"password|secret|access_token|refresh_token|api_key|authorization_header", str(k), re.I) or has_credentials(v) for k,v in value.items())
        return isinstance(value, list) and any(has_credentials(v) for v in value)
    if has_credentials(payload.draft):
        raise HTTPException(422, "Do not include passwords, API keys or access tokens in onboarding drafts.")
    # Values in this bag are never fed to the agent or promoted to profile_data.
    db.query(type(profile)).filter(type(profile).id == profile.id).with_for_update().one()
    db.refresh(profile)
    state = deepcopy(records(profile))
    previous = state.get(payload.card, {})
    if payload.resume and not previous:
        raise HTTPException(409, "This card has no saved draft. Open the review before resuming it.")
    value = {"deferred": not payload.resume, "resumed": payload.resume, "draft": payload.draft if not payload.resume else previous.get("draft", {}), "actor_user_id": actor.id, "updated_at": datetime.utcnow().isoformat()}
    if previous.get("deferred") == value["deferred"] and previous.get("draft") == value["draft"]:
        return state
    state[payload.card] = value
    profile.field_sources = {**(profile.field_sources or {}), KEY: state}
    flag_modified(profile, "field_sources")
    if prefix == "field":
        if scope == "project":
            from app.modules.projects import services
        else:
            from app.modules.company_onboarding import services
        keys = [identifier]
        if scope == "project" and identifier == "sales_contacts": keys.append("appointment_routing")
        if scope == "project" and identifier in {"campaigns_defined", "meta_connection_verified"}: keys = ["campaigns_defined", "meta_connection_verified"]
        updates = [{"field":key, "value":None, "status":"missing" if payload.resume else "deferred", "applicable":True} for key in keys if (profile.field_states or {}).get(key, {}).get("status") not in {"confirmed", "corrected_by_user"}]
        if updates:
            services.apply_field_updates(db, profile, updates, allow_authoritative_statuses=True, actor_user_id=actor.id, commit=False)
    # Evidence remains in the ordinary chat, independent of the current UI.
    session = (db.query(cm.OnboardingSession).filter_by(company_id=entity_id).one() if scope == "company" else profile.project.session)
    message_model = cm.OnboardingMessage if scope == "company" else pm.ProjectMessage
    sender = cm.SenderType.AI if scope == "company" else pm.SenderType.AI
    label = fields[identifier].label if prefix == "field" else {"source":"Document review", "property":"Property type draft"}.get(prefix, payload.card.replace("_", " "))
    db.add(message_model(session_id=session.id, sender=sender, content=("Resumed " if payload.resume else "Configured for later: ") + label + ". Saved values were preserved. This does not approve data, files or sales permissions.", response_payload={"status":"resumed" if payload.resume else "deferred", "answer":payload.card, "draft_snapshot":deepcopy(value["draft"]), "actor_user_id":actor.id, "decided_at":value["updated_at"]}))
    record_platform_event(db, actor=actor, company_id=company_id, event_type="onboarding.card_resumed" if payload.resume else "onboarding.card_deferred", entity_type=scope + "_profile", entity_id=profile.id, payload={"card":payload.card,"before":previous,"after":value})
    db.commit()
    return records(profile)


@router.post("/{scope}/{entity_id}")
def decide(scope: Literal["company", "project"], entity_id: str, payload: Decision, db: Session = Depends(get_db), actor: User = Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    if scope == "company":
        if entity_id != actor.company_id:
            raise HTTPException(404, "Company not found.")
        from app.modules.company_onboarding import services
        services.get_or_create_session(db, entity_id)
        profile = services.get_or_create_profile(db, entity_id)
    else:
        from app.modules.projects import services
        from app.modules.users.project_access import require_project_access
        require_project_access(db, actor, entity_id)
        profile = services.get_profile(services.get_project(db, entity_id, actor.company_id))
    return {"deferrals": save(db, profile, scope, entity_id, payload, actor)}
