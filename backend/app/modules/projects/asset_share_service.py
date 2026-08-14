from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings

from .models import ProjectOnboardingSource, SalesAssetShare


def issue(db: Session, *, company_id: str, project_id: str, lead_id: str, source_id: str) -> str:
    expires_at = datetime.utcnow() + timedelta(days=7)
    nonce = secrets.token_urlsafe(24)
    payload = f"{company_id}.{project_id}.{lead_id}.{source_id}.{int(expires_at.timestamp())}.{nonce}"
    signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}.{signature}"
    share = SalesAssetShare(
        company_id=company_id, project_id=project_id, lead_id=lead_id, source_id=source_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires_at,
    )
    db.add(share); db.flush()
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1/projects/shared-assets/{token}"


def resolve(db: Session, token: str) -> ProjectOnboardingSource:
    parts = token.split(".")
    if len(parts) != 7:
        raise HTTPException(status_code=404, detail="Shared image not found.")
    payload, signature = ".".join(parts[:-1]), parts[-1]
    expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=404, detail="Shared image not found.")
    share = db.query(SalesAssetShare).filter(
        SalesAssetShare.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        SalesAssetShare.revoked.is_(False),
        SalesAssetShare.expires_at > datetime.utcnow(),
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="This shared image is unavailable or expired.")
    source = db.query(ProjectOnboardingSource).filter(
        ProjectOnboardingSource.id == share.source_id,
        ProjectOnboardingSource.project_id == share.project_id,
        ProjectOnboardingSource.storage_path.isnot(None),
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="Shared image not found.")
    share.access_count += 1; share.last_accessed_at = datetime.utcnow(); db.add(share); db.commit()
    return source
