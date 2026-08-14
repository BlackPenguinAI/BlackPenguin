import base64
from datetime import datetime
import hashlib

from cryptography.fernet import Fernet
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings

from .models import MetaConnection, Project, ProjectCampaign


def _fernet() -> Fernet:
    # Derive a stable encryption key from the platform secret. Rotate with a dedicated key in a future vault migration.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def create_connection(db: Session, *, company_id: str, payload: dict) -> MetaConnection:
    payload = dict(payload)
    token = payload.pop("access_token")
    connection = MetaConnection(
        company_id=company_id,
        token_ciphertext=_fernet().encrypt(token.encode("utf-8")).decode("ascii"),
        token_hint=f"••••{token[-4:]}",
        verification_mode="real",
        verification_status="pending",
        **payload,
    )
    db.add(connection); db.commit(); db.refresh(connection)
    return connection


async def verify_connection(db: Session, connection: MetaConnection) -> MetaConnection:
    if not connection.token_ciphertext:
        raise ValueError("A real access token is required for live verification.")
    token = _fernet().decrypt(connection.token_ciphertext.encode("ascii")).decode("utf-8")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://graph.facebook.com/{settings.META_API_VERSION}/me",
            params={"access_token": token, "fields": "id,name"}, timeout=20.0,
        )
        response.raise_for_status()
    connection.verified_at = datetime.utcnow()
    connection.verification_mode = "real"
    connection.verification_status = "succeeded"
    connection.verification_results = {"identity_check": "passed"}
    db.add(connection); db.commit(); db.refresh(connection)
    return connection


def simulate_project_setup(
    db: Session,
    *,
    project: Project,
    page_id: str,
    ad_account_id: str,
    lead_form_id: str,
    page_access_confirmed: bool,
    ad_account_access_confirmed: bool,
    leads_access_confirmed: bool,
) -> tuple[MetaConnection, ProjectCampaign]:
    """Persist a resumable Meta setup without inventing or storing credentials."""
    if not all((page_access_confirmed, ad_account_access_confirmed, leads_access_confirmed)):
        raise ValueError("Confirm every Meta asset-access step before testing the setup.")
    for label, value in (
        ("Page ID", page_id),
        ("Ad Account ID", ad_account_id),
        ("Form ID", lead_form_id),
    ):
        normalized = value.removeprefix("act_").strip()
        if not normalized.isdigit() or not 5 <= len(normalized) <= 32:
            raise ValueError(f"{label} must contain between 5 and 32 digits.")
    page_id = page_id.strip()
    ad_account_id = ad_account_id.removeprefix("act_").strip()
    lead_form_id = lead_form_id.strip()
    connection = db.query(MetaConnection).filter(
        MetaConnection.company_id == project.company_id,
        MetaConnection.page_id == page_id,
        MetaConnection.ad_account_id == ad_account_id,
        MetaConnection.verification_mode == "simulated",
    ).first()
    now = datetime.utcnow()
    if not connection:
        connection = MetaConnection(
            company_id=project.company_id,
            label=f"Meta Lead Ads · {project.name}"[:120],
            page_id=page_id,
            ad_account_id=ad_account_id,
            token_ciphertext=None,
            token_hint=None,
            verification_mode="simulated",
        )
    connection.verification_status = "succeeded"
    connection.verification_results = {
        "simulated": True,
        "checks": ["page_id", "ad_account_id", "lead_form_id", "asset_access_confirmations"],
    }
    connection.page_access_confirmed = page_access_confirmed
    connection.ad_account_access_confirmed = ad_account_access_confirmed
    connection.leads_access_confirmed = leads_access_confirmed
    connection.simulated_verified_at = now
    db.add(connection)
    db.flush()
    campaign = db.query(ProjectCampaign).filter(
        ProjectCampaign.project_id == project.id,
        ProjectCampaign.platform == "meta",
        ProjectCampaign.lead_form_id == lead_form_id,
    ).first()
    if not campaign:
        campaign = ProjectCampaign(
            project_id=project.id,
            name=f"Meta Lead Ads · {project.name}"[:180],
            platform="meta",
            status="draft",
            lead_form_id=lead_form_id,
        )
    campaign.meta_connection_id = connection.id
    db.add(campaign)
    db.commit()
    db.refresh(connection)
    db.refresh(campaign)
    return connection, campaign
