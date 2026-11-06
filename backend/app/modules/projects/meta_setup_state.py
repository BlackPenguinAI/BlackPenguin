"""Read account permission and Project routing state independently; no credentials."""
from datetime import datetime
from sqlalchemy.orm import Session
from .models import MetaAuthorization, MetaConnection, Project, ProjectCampaign
from .meta_oauth_service import serialize_authorization

REQUIRED_SCOPES = {"pages_show_list", "pages_manage_metadata", "pages_manage_ads", "leads_retrieval", "ads_read"}


def setup_state(db: Session, project: Project) -> dict:
    now = datetime.utcnow()
    authorizations = db.query(MetaAuthorization).filter_by(company_id=project.company_id).all()
    authorizations.sort(key=lambda a: (a.created_at, a.id), reverse=True)
    live = [a for a in authorizations if a.status == "active" and (a.expires_at is None or a.expires_at > now)]
    usable = [a for a in live if REQUIRED_SCOPES.issubset(set(a.scopes or []))]
    status = "connected" if usable else "permissions_required" if live else "reconnect_required" if authorizations else "not_connected"
    mappings = []
    for campaign in db.query(ProjectCampaign).filter_by(project_id=project.id, platform="meta").order_by(ProjectCampaign.created_at).all():
        connection = db.get(MetaConnection, campaign.meta_connection_id) if campaign.meta_connection_id else None
        ready = bool(campaign.status == "active" and connection and connection.company_id == project.company_id
            and connection.verification_mode == "real" and connection.verification_status == "succeeded"
            and (connection.expires_at is None or connection.expires_at > now)
            and (not connection.authorization_id or connection.authorization_id in {a.id for a in usable})
            and connection.page_id and campaign.lead_form_id)
        reason = ("ready" if ready else "inactive_campaign" if campaign.status != "active"
                  else "connection_required" if not connection or connection.company_id != project.company_id
                  else "real_verification_required" if connection.verification_mode != "real" or connection.verification_status != "succeeded"
                  else "connection_expired" if connection.expires_at and connection.expires_at <= now
                  else "authorization_required" if connection.authorization_id and connection.authorization_id not in {a.id for a in usable}
                  else "page_or_form_required")
        mappings.append({"id": campaign.id, "name": campaign.name, "campaign_status": campaign.status, "reason": reason,
            "page_id": connection.page_id if connection and connection.company_id == project.company_id else None,
            "lead_form_id": campaign.lead_form_id, "ready": ready,
            "verification_mode": connection.verification_mode if connection and connection.company_id == project.company_id else None})
    best = (usable or sorted(live, key=lambda a: len(REQUIRED_SCOPES - set(a.scopes or []))) or authorizations)
    return {"project_id": project.id, "account_status": status,
        "last_authorization": serialize_authorization(best[0]) if best else None,
        "authorizations": [serialize_authorization(a) for a in live],
        "missing_permissions": sorted(REQUIRED_SCOPES - set(best[0].scopes or [])) if live and not usable else [],
        "routing_status": "connected" if any(m["ready"] for m in mappings) else "review_required" if mappings else "not_linked",
        "mappings": mappings}
