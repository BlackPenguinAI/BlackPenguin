from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.governance.models import SalesAssetAccessEvent
from app.modules.governance.services import enqueue_notification

from .models import ProjectOnboardingSource, ProjectSalesAsset, SalesAssetShare


def _event_hash(db: Session, payload: dict) -> tuple[str | None, str]:
    previous = db.query(SalesAssetAccessEvent).order_by(
        SalesAssetAccessEvent.created_at.desc(), SalesAssetAccessEvent.id.desc(),
    ).first()
    previous_hash = previous.event_hash if previous else None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    value = hashlib.sha256(f"{previous_hash or ''}|{canonical}".encode()).hexdigest()
    return previous_hash, value


def record_event(
    db: Session, *, share: SalesAssetShare, event_type: str,
    ip_hash: str | None = None, user_agent_hash: str | None = None,
    is_automated: bool = False,
) -> SalesAssetAccessEvent:
    asset = db.query(ProjectSalesAsset).filter(ProjectSalesAsset.id == share.sales_asset_id).first() if share.sales_asset_id else None
    created_at = datetime.utcnow()
    payload = {
        "share_id": share.id,
        "company_id": share.company_id,
        "project_id": share.project_id,
        "lead_id": share.lead_id,
        "sales_asset_id": share.sales_asset_id,
        "source_id": share.source_id,
        "outbound_message_id": share.outbound_message_id,
        "channel": share.channel,
        "asset_type": asset.asset_type if asset else None,
        "asset_name": asset.display_name if asset else None,
        "event_type": event_type,
        "ip_hash": ip_hash,
        "user_agent_hash": user_agent_hash,
        "is_automated": is_automated,
        "created_at": created_at.isoformat(timespec="microseconds"),
        "nonce": secrets.token_hex(8),
    }
    previous_hash, event_hash = _event_hash(db, payload)
    event = SalesAssetAccessEvent(
        **{key: value for key, value in payload.items() if key not in {"created_at", "nonce"}},
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    db.add(event)
    return event


def issue(
    db: Session, *, company_id: str, project_id: str, lead_id: str,
    source_id: str, sales_asset_id: str | None = None, channel: str | None = None,
    agent_run_id: str | None = None, expires_in_days: int = 7,
    target_url: str | None = None,
) -> tuple[str, SalesAssetShare]:
    """Issue a short opaque token. The raw token never persists in storage."""
    token = secrets.token_urlsafe(18)
    share = SalesAssetShare(
        company_id=company_id,
        project_id=project_id,
        lead_id=lead_id,
        source_id=source_id,
        sales_asset_id=sales_asset_id,
        agent_run_id=agent_run_id,
        channel=channel,
        target_url=target_url,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(days=max(1, min(expires_in_days, 30))),
    )
    db.add(share)
    db.flush()
    record_event(db, share=share, event_type="link_issued")
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}{settings.API_V1_STR}/projects/a/{token}", share


def _legacy_token_valid(token: str) -> bool:
    parts = token.split(".")
    if len(parts) != 7:
        return False
    payload, signature = ".".join(parts[:-1]), parts[-1]
    expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def resolve(db: Session, token: str) -> tuple[ProjectOnboardingSource, SalesAssetShare]:
    # Signed legacy links remain valid until their original expiry.
    if "." in token and not _legacy_token_valid(token):
        raise HTTPException(status_code=404, detail="Shared sales material not found.")
    share = db.query(SalesAssetShare).filter(
        SalesAssetShare.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        SalesAssetShare.revoked.is_(False),
        SalesAssetShare.expires_at > datetime.utcnow(),
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="This shared sales material is unavailable or expired.")
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == share.source_id,
        ProjectOnboardingSource.project_id == share.project_id,
    ).first()
    if not source or (not share.target_url and not source.storage_path):
        raise HTTPException(status_code=404, detail="Shared sales material not found.")
    return source, share


def record_access(
    db: Session, *, share: SalesAssetShare, event_type: str,
    ip_hash: str | None, user_agent_hash: str | None, user_agent: str | None,
) -> None:
    automated = any(value in (user_agent or "").casefold() for value in (
        "bot", "crawler", "spider", "preview", "slackbot", "whatsapp", "facebookexternalhit",
    ))
    now = datetime.utcnow()
    share.access_count += 1
    share.last_accessed_at = now
    record_event(
        db, share=share,
        event_type="automated_preview" if automated else ("human_view" if event_type == "view" else event_type),
        ip_hash=ip_hash, user_agent_hash=user_agent_hash, is_automated=automated,
    )
    if not automated and share.first_human_access_at is None:
        share.first_human_access_at = now
        enqueue_notification(
            db, company_id=share.company_id, project_id=share.project_id,
            event_type="asset_high_interest", entity_type="lead", entity_id=share.lead_id,
            payload={
                "title": "Sales material opened",
                "body": "A lead opened shared sales material. This may indicate high interest.",
                "action_url": f"/app/leads?lead={share.lead_id}",
            }, dedupe_key=f"asset-first-human:{share.id}",
        )
    db.add(share)
    db.commit()


def revoke(db: Session, share: SalesAssetShare, *, user_id: str) -> None:
    if share.revoked:
        return
    share.revoked = True
    share.revoked_at = datetime.utcnow()
    share.revoked_by_user_id = user_id
    record_event(db, share=share, event_type="revoked")
    db.add(share)
    db.commit()
