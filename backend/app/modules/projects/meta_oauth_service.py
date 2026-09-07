from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.secret_store import decrypt_secret, encrypt_secret
from app.modules.system_settings import services as system_settings
from app.modules.system_settings.models import MetaOAuthAttempt
from app.modules.users.models import User

from .models import MetaAuthorization, MetaConnection, Project, ProjectCampaign


def _token(authorization: MetaAuthorization) -> str:
    try:
        return decrypt_secret(authorization.token_ciphertext) or ""
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Reconnect Meta because its stored authorization cannot be decrypted.") from exc


def _ensure_required_scopes(authorization: MetaAuthorization) -> None:
    required = {"pages_show_list", "pages_manage_metadata", "leads_retrieval", "ads_read"}
    missing = sorted(required.difference(authorization.scopes or []))
    if missing:
        raise HTTPException(status_code=422, detail=f"Reconnect Meta and grant the required permissions: {', '.join(missing)}.")


def start_oauth(db: Session, *, project: Project, user: User) -> dict:
    config, _ = system_settings.meta_platform_credentials(db)
    state = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.add(MetaOAuthAttempt(
        user_id=user.id, company_id=project.company_id, project_id=project.id,
        nonce_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(), expires_at=expires_at,
    ))
    db.commit()
    params = {
        "client_id": config.app_id,
        "redirect_uri": config.redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": ",".join(config.requested_scopes or system_settings.META_OAUTH_SCOPES),
        "config_id": config.login_config_id,
    }
    return {
        "authorization_url": f"https://www.facebook.com/{config.graph_api_version}/dialog/oauth?{urlencode(params)}",
        "expires_at": expires_at,
    }


async def complete_oauth(db: Session, *, state: str, code: str) -> tuple[MetaAuthorization, str]:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    attempt = db.query(MetaOAuthAttempt).filter(
        MetaOAuthAttempt.nonce_hash == digest,
        MetaOAuthAttempt.consumed_at.is_(None),
        MetaOAuthAttempt.expires_at > datetime.utcnow(),
    ).first()
    if not attempt:
        raise HTTPException(status_code=400, detail="This Meta connection attempt is invalid or expired.")
    attempt.consumed_at = datetime.utcnow()
    db.add(attempt); db.commit()
    config, secret = system_settings.meta_platform_credentials(db)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"https://graph.facebook.com/{config.graph_api_version}/oauth/access_token",
            params={
                "client_id": config.app_id, "client_secret": secret,
                "redirect_uri": config.redirect_uri, "code": code,
            },
        )
        response.raise_for_status()
        token_payload = response.json()
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise HTTPException(status_code=422, detail="Meta did not return an access token.")
        exchange = await client.get(
            f"https://graph.facebook.com/{config.graph_api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token", "client_id": config.app_id,
                "client_secret": secret, "fb_exchange_token": access_token,
            },
        )
        if exchange.is_success and exchange.json().get("access_token"):
            token_payload = exchange.json()
            access_token = str(token_payload["access_token"])
        identity = await client.get(
            f"https://graph.facebook.com/{config.graph_api_version}/me",
            params={"access_token": access_token, "fields": "id,name"},
        )
        identity.raise_for_status()
        person = identity.json()
        permissions = await client.get(
            f"https://graph.facebook.com/{config.graph_api_version}/me/permissions",
            params={"access_token": access_token},
        )
        permissions.raise_for_status()
        granted_scopes = [
            str(item.get("permission")) for item in permissions.json().get("data", [])
            if item.get("status") == "granted" and item.get("permission")
        ]
    meta_user_id = str(person.get("id") or "")
    if not meta_user_id:
        raise HTTPException(status_code=422, detail="Meta did not return the authorized user identity.")
    authorization = db.query(MetaAuthorization).filter(
        MetaAuthorization.company_id == attempt.company_id,
        MetaAuthorization.meta_user_id == meta_user_id,
    ).first() or MetaAuthorization(company_id=attempt.company_id, meta_user_id=meta_user_id, token_ciphertext="")
    authorization.connected_by_user_id = attempt.user_id
    authorization.meta_user_name = person.get("name")
    authorization.token_ciphertext = encrypt_secret(access_token)
    authorization.token_hint = f"••••{access_token[-4:]}"
    authorization.scopes = granted_scopes
    expires_in = int(token_payload.get("expires_in") or 0)
    authorization.expires_at = datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None
    authorization.status = "active"
    authorization.verification_results = {"identity_check": "passed", "connected_at": datetime.utcnow().isoformat()}
    db.add(authorization); db.commit(); db.refresh(authorization)
    return authorization, attempt.project_id


def serialize_authorization(item: MetaAuthorization) -> dict:
    return {
        "id": item.id, "meta_user_id": item.meta_user_id,
        "meta_user_name": item.meta_user_name, "scopes": item.scopes or [],
        "expires_at": item.expires_at, "status": item.status, "created_at": item.created_at,
    }


def authorizations(db: Session, company_id: str) -> list[MetaAuthorization]:
    return db.query(MetaAuthorization).filter(
        MetaAuthorization.company_id == company_id,
        MetaAuthorization.status == "active",
        or_(MetaAuthorization.expires_at.is_(None), MetaAuthorization.expires_at > datetime.utcnow()),
    ).order_by(MetaAuthorization.created_at.desc()).all()


async def discover_assets(
    db: Session, *, company_id: str, authorization_id: str,
    page_id: str | None = None, ad_account_id: str | None = None,
) -> dict:
    authorization = db.query(MetaAuthorization).filter(
        MetaAuthorization.id == authorization_id,
        MetaAuthorization.company_id == company_id,
        MetaAuthorization.status == "active",
        or_(MetaAuthorization.expires_at.is_(None), MetaAuthorization.expires_at > datetime.utcnow()),
    ).first()
    if not authorization:
        raise HTTPException(status_code=404, detail="Meta authorization not found for this Company.")
    _ensure_required_scopes(authorization)
    config, _ = system_settings.meta_platform_credentials(db)
    token = _token(authorization)
    base = f"https://graph.facebook.com/{config.graph_api_version}"
    async with httpx.AsyncClient(timeout=25.0) as client:
        pages_response = await client.get(f"{base}/me/accounts", params={
            "access_token": token,
            "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 200,
        })
        pages_response.raise_for_status()
        pages_raw = pages_response.json().get("data", [])
        ad_accounts_response = await client.get(f"{base}/me/adaccounts", params={
            "access_token": token, "fields": "id,account_id,name,account_status", "limit": 200,
        })
        ad_accounts_response.raise_for_status()
        ad_accounts_raw = ad_accounts_response.json().get("data", [])
        forms_raw: list[dict] = []
        page = next((item for item in pages_raw if str(item.get("id")) == str(page_id)), None)
        if page_id:
            if not page:
                raise HTTPException(status_code=422, detail="The selected Page is not available to this Meta authorization.")
            forms_response = await client.get(f"{base}/{page_id}/leadgen_forms", params={
                "access_token": page.get("access_token") or token, "fields": "id,name,status", "limit": 200,
            })
            forms_response.raise_for_status()
            forms_raw = forms_response.json().get("data", [])
        campaigns_raw: list[dict] = []
        adsets_raw: list[dict] = []
        ads_raw: list[dict] = []
        if ad_account_id:
            normalized = str(ad_account_id).removeprefix("act_")
            account = next((item for item in ad_accounts_raw if str(item.get("account_id") or item.get("id", "").removeprefix("act_")) == normalized), None)
            if not account:
                raise HTTPException(status_code=422, detail="The selected Ad Account is not available to this Meta authorization.")
            account_path = str(account.get("id") or f"act_{normalized}")
            for edge, target in (("campaigns", campaigns_raw), ("adsets", adsets_raw), ("ads", ads_raw)):
                edge_response = await client.get(f"{base}/{account_path}/{edge}", params={
                    "access_token": token, "fields": "id,name,status", "limit": 200,
                })
                edge_response.raise_for_status()
                target.extend(edge_response.json().get("data", []))
    option = lambda item: {
        "id": str(item.get("account_id") or item.get("id") or ""),
        "name": str(item.get("name") or item.get("id") or ""),
        "status": str(item.get("status") or item.get("account_status") or "") or None,
    }
    pages = []
    for item in pages_raw:
        instagram = item.get("instagram_business_account") or {}
        pages.append({
            **option(item), "instagram_account_id": str(instagram.get("id") or "") or None,
            "instagram_username": instagram.get("username"),
        })
    return {
        "authorizations": [serialize_authorization(item) for item in authorizations(db, company_id)],
        "pages": pages, "ad_accounts": [option(item) for item in ad_accounts_raw],
        "lead_forms": [option(item) for item in forms_raw],
        "campaigns": [option(item) for item in campaigns_raw],
        "adsets": [option(item) for item in adsets_raw], "ads": [option(item) for item in ads_raw],
    }


def configure_project_setup(
    db: Session, *, project: Project, authorization_id: str, page_id: str,
    ad_account_id: str, lead_form_id: str, campaign_name: str,
    external_campaign_id: str | None = None, external_adset_id: str | None = None,
    external_ad_id: str | None = None, instagram_account_id: str | None = None,
    business_account_id: str | None = None, commit: bool = True,
) -> tuple[MetaConnection, ProjectCampaign]:
    authorization = db.query(MetaAuthorization).filter(
        MetaAuthorization.id == authorization_id,
        MetaAuthorization.company_id == project.company_id,
        MetaAuthorization.status == "active",
        or_(MetaAuthorization.expires_at.is_(None), MetaAuthorization.expires_at > datetime.utcnow()),
    ).first()
    if not authorization:
        raise HTTPException(status_code=404, detail="Meta authorization not found for this Company.")
    _ensure_required_scopes(authorization)
    config, _ = system_settings.meta_platform_credentials(db)
    token = _token(authorization)
    base = f"https://graph.facebook.com/{config.graph_api_version}"
    with httpx.Client(timeout=25.0) as client:
        try:
            pages_response = client.get(f"{base}/me/accounts", params={
                "access_token": token, "fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 200,
            })
            pages_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail="Meta could not validate the selected assets. Reconnect Meta and try again.") from exc
        page = next((item for item in pages_response.json().get("data", []) if str(item.get("id")) == page_id), None)
        if not page:
            raise HTTPException(status_code=422, detail="The selected Page is no longer available.")
        page_token = str(page.get("access_token") or token)
        accounts_response = client.get(f"{base}/me/adaccounts", params={
            "access_token": token, "fields": "id,account_id,name,account_status", "limit": 200,
        })
        try:
            accounts_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail="Meta could not validate the selected Ad Account.") from exc
        normalized_ad_account = ad_account_id.removeprefix("act_")
        account = next((item for item in accounts_response.json().get("data", [])
                        if str(item.get("account_id") or item.get("id", "").removeprefix("act_")) == normalized_ad_account), None)
        if not account:
            raise HTTPException(status_code=422, detail="The selected Ad Account is no longer available.")
        forms_response = client.get(f"{base}/{page_id}/leadgen_forms", params={
            "access_token": page_token, "fields": "id,name,status", "limit": 200,
        })
        try:
            forms_response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail="Meta could not load Lead Forms for the selected Page.") from exc
        form = next((item for item in forms_response.json().get("data", []) if str(item.get("id")) == lead_form_id), None)
        if not form:
            raise HTTPException(status_code=422, detail="The selected Lead Form is no longer available.")
        subscription = client.post(f"{base}/{page_id}/subscribed_apps", data={
            "access_token": page_token, "subscribed_fields": "leadgen",
        })
        try:
            subscription.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=422, detail="Black Penguin could not subscribe the selected Page to lead events. Check Leads Access in Meta.") from exc
    connection = db.query(MetaConnection).filter(
        MetaConnection.company_id == project.company_id,
        MetaConnection.authorization_id == authorization.id,
        MetaConnection.page_id == page_id,
        MetaConnection.ad_account_id == normalized_ad_account,
    ).first() or MetaConnection(
        company_id=project.company_id,
        label=f"{page.get('name') or 'Meta Page'} · {normalized_ad_account}"[:120],
        authorization_id=authorization.id,
    )
    connection.business_account_id = business_account_id
    connection.page_id = page_id
    connection.ad_account_id = normalized_ad_account
    connection.instagram_account_id = instagram_account_id or (page.get("instagram_business_account") or {}).get("id")
    connection.token_ciphertext = encrypt_secret(page_token)
    connection.token_hint = f"••••{page_token[-4:]}"
    connection.scopes = authorization.scopes
    connection.expires_at = authorization.expires_at
    connection.verified_at = datetime.utcnow()
    connection.verification_mode = "real"
    connection.verification_status = "succeeded"
    connection.verification_results = {"identity_check": "passed", "page": "passed", "lead_form": "passed", "leadgen_subscription": "passed"}
    connection.page_access_confirmed = True
    connection.ad_account_access_confirmed = True
    connection.leads_access_confirmed = True
    db.add(connection); db.flush()
    campaign = db.query(ProjectCampaign).filter(
        ProjectCampaign.project_id == project.id,
        ProjectCampaign.platform == "meta",
        ProjectCampaign.lead_form_id == lead_form_id,
        ProjectCampaign.external_ad_id == external_ad_id,
    ).first() or ProjectCampaign(project_id=project.id, platform="meta", name=campaign_name[:180])
    campaign.name = campaign_name.strip()[:180]
    campaign.status = "active"
    campaign.meta_connection_id = connection.id
    campaign.lead_form_id = lead_form_id
    campaign.external_campaign_id = external_campaign_id
    campaign.external_adset_id = external_adset_id
    campaign.external_ad_id = external_ad_id
    db.add(campaign)
    if commit:
        db.commit(); db.refresh(connection); db.refresh(campaign)
    else:
        db.flush()
    return connection, campaign
