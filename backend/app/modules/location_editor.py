"""Explicit selectable location review; suggestions never become facts by reading."""
import json
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, TENANT_MANAGER_ROLES
from app.modules.companies.models import Company
from app.modules.users.project_access import require_project_access

router=APIRouter()
OPTIONS=json.loads(Path(__file__).with_name("location_options.json").read_text())
def norm(text):
    return "".join(c for c in unicodedata.normalize("NFKD",str(text or "")) if not unicodedata.combining(c)).casefold().strip()
def country_code(value):
    aliases={"peru":"PE","mexico":"MX","united states":"US","usa":"US","estados unidos":"US","brasil":"BR","brazil":"BR","argentina":"AR","reino unido":"GB"}
    return next((k for k,v in OPTIONS["countries"].items() if norm(value) in {norm(k),norm(v)}),aliases.get(norm(value)))

def validate_published_location(data):
    """Protect approval through generic profile APIs as well as the editor."""
    zone=data.get("timezone")
    if not zone: return
    code=country_code(data.get("country"))
    valid={i["timezone"] for i in OPTIONS["cities"] if i["country"]==code}
    city_zones={i["timezone"] for i in OPTIONS["cities"] if i["country"]==code and norm(i["city"])==norm(data.get("city"))}
    if not code or zone not in valid or city_zones and zone not in city_zones:
        raise HTTPException(422,"Review country, city and timezone together before approving this profile.")

class LocationDecision(BaseModel):
    country: str
    city: str = Field(min_length=1,max_length=100)
    timezone: str

def owner(db,scope,entity,actor):
    if scope=="project":
        from app.modules.projects import services
        require_project_access(db,actor,entity)
        p=services.get_project(db,entity,actor.company_id)
        return services,p.profile,p
    if scope!="company" or entity!=actor.company_id:raise HTTPException(404,"Onboarding not found.")
    from app.modules.company_onboarding import services
    return services,services.get_or_create_profile(db,entity),db.get(Company,entity)

@router.get("/{scope}/{entity}/location")
def suggestions(scope:str,entity:str,db:Session=Depends(get_db),actor:User=Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    services,profile,record=owner(db,scope,entity,actor)
    data=profile.profile_data or {}
    company=db.get(Company,actor.company_id)
    country=country_code(data.get("country") or getattr(record,"country",None))
    city=data.get("city") or getattr(record,"city",None) or ""
    source="Saved profile (review before confirming)"
    if scope in {"project","company"}:
        if scope=="project":
            from app.modules.projects.models import ProjectOnboardingSource as Source
            source_query=db.query(Source).filter_by(project_id=entity)
        else:
            from app.modules.company_onboarding.models import CompanyOnboardingSource as Source
            source_query=db.query(Source).filter_by(company_id=entity)
        # Do not replace a confirmed location with a new extraction.
        if (profile.field_states or {}).get("country",{}).get("status") not in {"confirmed","corrected_by_user"}:
            for item in source_query.order_by(Source.created_at.desc()).all():
                proposed={p.field_key:p.value for p in item.proposals if p.status.value!="rejected"}
                if isinstance(proposed.get("headquarters"),dict):
                    proposed={**proposed["headquarters"],**proposed}
                candidate=country_code(proposed.get("country"))
                if candidate:
                    country=candidate;city=proposed.get("city") or city;source=item.name;break
    if not country:
        country=country_code(company.country_code);source="Company country suggestion (not approved for this Project)"
    elif scope == "project" and not data.get("country") and source.startswith("Saved profile"):
        source="Company country suggestion (not approved for this Project)"
    matches=[i for i in OPTIONS["cities"] if i["country"]==country and norm(i["city"])==norm(city)]
    zones=sorted({i["timezone"] for i in matches})
    return {"countries":[{"code":k,"name":v} for k,v in sorted(OPTIONS["countries"].items(),key=lambda i:i[1])],
        "cities":OPTIONS["cities"],"country":country or "","city":city,"source":source,
        "timezone":data.get("timezone") or (zones[0] if len(zones)==1 else ""),
        "timezone_confirmed":(profile.field_states or {}).get("timezone",{}).get("status") in {"confirmed","corrected_by_user"}}

@router.post("/{scope}/{entity}/location")
def confirm(scope:str,entity:str,payload:LocationDecision,db:Session=Depends(get_db),actor:User=Depends(RoleChecker(TENANT_MANAGER_ROLES))):
    services,profile,record=owner(db,scope,entity,actor)
    code=country_code(payload.country)
    if not code:raise HTTPException(422,"Choose a valid country.")
    city=payload.city.strip()
    if not city:raise HTTPException(422,"Choose or enter the city.")
    try:ZoneInfo(payload.timezone)
    except (ValueError,ZoneInfoNotFoundError):raise HTTPException(422,"Choose a valid IANA timezone.")
    country_zones={i["timezone"] for i in OPTIONS["cities"] if i["country"]==code}
    if payload.timezone not in country_zones:raise HTTPException(422,"Choose a timezone listed for this country.")
    matches={i["timezone"] for i in OPTIONS["cities"] if i["country"]==code and norm(i["city"])==norm(city)}
    if matches and payload.timezone not in matches:raise HTTPException(422,"The selected timezone does not match the selected city.")
    updates=[{"field":k,"value":v,"status":"confirmed","applicable":True,"source_type":"user","source_reference":"location_editor","confidence":"high"} for k,v in [("country",code),("city",city),("timezone",payload.timezone)]]
    result=services.apply_field_updates(db,profile,updates,allow_authoritative_statuses=True,actor_user_id=actor.id,commit=False)
    if result.rejected:db.rollback();raise HTTPException(422,"Location could not be confirmed. No changes were saved.")
    # Project timezone is published only on profile approval; existing meeting instants never change.
    db.commit()
    return {"saved":True,"message":"Location saved for review. Approve the profile to publish Project changes; existing appointments are unchanged."}

