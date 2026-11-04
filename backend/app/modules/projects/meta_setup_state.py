"""Read account permission and Project routing state independently; no credentials."""
from datetime import datetime
from sqlalchemy.orm import Session
from .models import MetaAuthorization, MetaConnection, Project, ProjectCampaign
from .meta_oauth_service import serialize_authorization

REQUIRED_SCOPES = {"pages_show_list", "pages_manage_metadata", "pages_manage_ads", "leads_retrieval", "ads_read"}


def setup_state(db: Session, project: Project) -> dict:
    now = datetime.utcnow()
    authorizations = db.query(MetaAuthorization).filter_by(company_id=project.company_id).all()
    live = [a for a in authorizations if a.status == "active" and (a.expires_at is None or a.expires_at > now)]
    usable = [a for a in live if REQUIRED_SCOPES.issubset(set(a.scopes or []))]
    status = "connected" if usable else "permissions_required" if live else "reconnect_required" if authorizations else "not_connected"
    mappings = []
    for campaign in db.query(ProjectCampaign).filter_by(project_id=project.id, platform="meta", status="active").all():
        connection = db.get(MetaConnection, campaign.meta_connection_id) if campaign.meta_connection_id else None
        ready = bool(connection and connection.company_id == project.company_id
            and connection.verification_mode == "real" and connection.verification_status == "succeeded"
            and (connection.expires_at is None or connection.expires_at > now)
            and (not connection.authorization_id or connection.authorization_id in {a.id for a in usable})
            and connection.page_id and campaign.lead_form_id)
        mappings.append({"id": campaign.id, "name": campaign.name,
            "page_id": connection.page_id if connection and connection.company_id == project.company_id else None,
            "lead_form_id": campaign.lead_form_id, "ready": ready,
            "verification_mode": connection.verification_mode if connection and connection.company_id == project.company_id else None})
    return {"project_id": project.id, "account_status": status,
        "authorizations": [serialize_authorization(a) for a in live],
        "missing_permissions": sorted(REQUIRED_SCOPES - set(live[0].scopes or [])) if live and not usable else [],
        "routing_status": "connected" if any(m["ready"] for m in mappings) else "review_required" if mappings else "not_linked",
        "mappings": mappings}
