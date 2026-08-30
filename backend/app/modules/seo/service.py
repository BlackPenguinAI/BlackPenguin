from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from .models import SeoAuditRun


CHECKS = {
    "title": r"<title>[^<]{10,}</title>",
    "description": r'<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{40,}["\']',
    "canonical": r'<link[^>]+rel=["\']canonical["\']',
    "open_graph": r'<meta[^>]+property=["\']og:title["\']',
    "structured_data": r'<script[^>]+type=["\']application/ld\+json["\']',
    "language": r'<html[^>]+lang=["\']en["\']',
}


def run_audit(db: Session) -> SeoAuditRun:
    target = settings.PUBLIC_APP_URL.rstrip("/") + "/"
    details: dict[str, object] = {}
    try:
        response = httpx.get(target, follow_redirects=True, timeout=15.0)
        response.raise_for_status()
        html = response.text
        for key, pattern in CHECKS.items():
            details[key] = bool(re.search(pattern, html, re.IGNORECASE | re.DOTALL))
        for asset in ("robots.txt", "sitemap.xml"):
            asset_response = httpx.get(urljoin(target, asset), follow_redirects=True, timeout=10.0)
            details[asset.replace(".", "_")] = asset_response.status_code == 200 and bool(asset_response.text.strip())
        score = round(100 * sum(value is True for value in details.values()) / len(details))
        status = "healthy" if score >= 90 else "needs_attention"
    except httpx.HTTPError as exc:
        details = {"fetch_error": type(exc).__name__}
        score = 0; status = "unreachable"
    item = SeoAuditRun(target_url=target, status=status, score=score, details=details)
    db.add(item); db.commit(); db.refresh(item); return item


def audits(db: Session, limit: int = 20) -> list[SeoAuditRun]:
    return db.query(SeoAuditRun).order_by(SeoAuditRun.created_at.desc()).limit(limit).all()
