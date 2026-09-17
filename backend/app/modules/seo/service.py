from __future__ import annotations

import re
import json
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from .models import SeoAuditRun


def _meta_content(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str:
    attrs = {"name": re.compile(f"^{re.escape(name)}$", re.I)} if name else {
        "property": re.compile(f"^{re.escape(prop or '')}$", re.I),
    }
    element = soup.find("meta", attrs=attrs)
    return str(element.get("content") or "").strip() if element else ""


def _valid_structured_data(soup: BeautifulSoup) -> bool:
    scripts = soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json$", re.I)})
    for script in scripts:
        try:
            if json.loads(script.string or script.get_text() or ""):
                return True
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return False


def _robots_allows_root(text: str) -> bool:
    active_wildcard = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().casefold(), value.strip()
        if key == "user-agent":
            active_wildcard = value == "*"
        elif active_wildcard and key == "disallow" and value == "/":
            return False
    return True


def _valid_sitemap(text: str) -> bool:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1].casefold() in {"urlset", "sitemapindex"}


def run_audit(db: Session) -> SeoAuditRun:
    target = settings.PUBLIC_APP_URL.rstrip("/") + "/"
    details: dict[str, object] = {}
    try:
        response = httpx.get(target, follow_redirects=True, timeout=15.0)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        description = _meta_content(soup, name="description")
        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        canonical_href = str(canonical.get("href") or "").strip() if canonical else ""
        robots_meta = _meta_content(soup, name="robots").casefold()
        details.update({
            "title": 10 <= len(title) <= 65,
            "description": 40 <= len(description) <= 170,
            "canonical": bool(canonical_href and urljoin(target, canonical_href).startswith(("http://", "https://"))),
            "open_graph": bool(_meta_content(soup, prop="og:title") and _meta_content(soup, prop="og:description")),
            "structured_data": _valid_structured_data(soup),
            "language": bool(soup.html and str(soup.html.get("lang") or "").strip()),
            "viewport": bool(_meta_content(soup, name="viewport")),
            "single_h1": len(soup.find_all("h1")) == 1,
            "indexable": "noindex" not in {item.strip() for item in robots_meta.split(",")},
            "https": target.startswith("https://"),
        })
        robots_response = httpx.get(urljoin(target, "robots.txt"), follow_redirects=True, timeout=10.0)
        details["robots_txt"] = (
            robots_response.status_code == 200
            and bool(robots_response.text.strip())
            and _robots_allows_root(robots_response.text)
        )
        sitemap_response = httpx.get(urljoin(target, "sitemap.xml"), follow_redirects=True, timeout=10.0)
        details["sitemap_xml"] = sitemap_response.status_code == 200 and _valid_sitemap(sitemap_response.text)
        score = round(100 * sum(value is True for value in details.values()) / len(details))
        critical_checks = ("title", "description", "canonical", "single_h1", "indexable", "https")
        status = "healthy" if score >= 90 and all(details.get(key) is True for key in critical_checks) else "needs_attention"
    except httpx.HTTPError as exc:
        details = {"fetch_error": type(exc).__name__}
        score = 0; status = "unreachable"
    item = SeoAuditRun(target_url=target, status=status, score=score, details=details)
    db.add(item); db.commit(); db.refresh(item); return item


def audits(db: Session, limit: int = 20) -> list[SeoAuditRun]:
    return db.query(SeoAuditRun).order_by(SeoAuditRun.created_at.desc()).limit(limit).all()
