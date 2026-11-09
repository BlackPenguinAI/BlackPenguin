"""Explicit per-property PDF/gallery publication using existing encrypted sales assets.

Gallery sources are immutable self-contained snapshots: selected images only,
no private file URLs, remote requests, executable user markup or scripts.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from html import escape
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from .models import ProjectOnboardingSource, ProjectSalesAsset, ProjectSourceKind, ProjectSourceStatus, SalesAssetShare
from . import storage_service

GALLERY_MIME = "application/vnd.blackpenguin.property-gallery+html"
MAX_GALLERY_BYTES = 40 * 1024 * 1024


def available(asset: ProjectSalesAsset) -> bool:
    now = datetime.utcnow()
    return bool(asset.approval_status == 'approved' and asset.approved_at and asset.allowed_channels
        and asset.project and asset.project.is_active and asset.project.company_id == asset.company_id
        and asset.source and asset.source.project_id == asset.project_id
        and asset.source.status == ProjectSourceStatus.READY and asset.source.storage_path
        and (not asset.property_type_id or (asset.property_type and asset.property_type.project_id == asset.project_id and asset.property_type.review_status == 'confirmed'))
        and (not asset.valid_from or asset.valid_from <= now)
        and (not asset.valid_until or asset.valid_until > now))


def _signature(asset: ProjectSalesAsset) -> str:
    payload = '|'.join(str(value or '') for value in (
        asset.company_id, asset.project_id, asset.property_type_id, asset.id,
        asset.source_id, asset.version, asset.approved_at, asset.source.content_hash,
    ))
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def resource_url(asset: ProjectSalesAsset) -> str | None:
    if not available(asset):
        return None
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}{settings.API_V1_STR}/projects/resources/{asset.id}/{_signature(asset)}"


def resolve_resource(db: Session, asset_id: str, signature: str) -> ProjectOnboardingSource:
    asset = db.get(ProjectSalesAsset, asset_id)
    if not asset or not available(asset) or not hmac.compare_digest(_signature(asset), signature):
        raise HTTPException(404, 'This property resource is unavailable.')
    return asset.source


def read_resource(source: ProjectOnboardingSource) -> tuple[bytes, str, dict[str, str]]:
    try:
        content = storage_service.read_project_file(source.storage_path, encrypted=bool(source.is_encrypted))
        if source.content_hash and hashlib.sha256(content).hexdigest() != source.content_hash:
            raise ValueError('Integrity check failed')
    except (OSError, ValueError):
        raise HTTPException(404, 'This property resource is unavailable.')
    headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}
    mime = source.mime_type or 'application/octet-stream'
    if mime == GALLERY_MIME:
        mime = 'text/html'
        headers['Content-Security-Policy'] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    return content, mime, headers


def revoke_asset_links(db: Session, asset: ProjectSalesAsset, *, user_id: str | None = None) -> None:
    from .asset_share_service import revoke
    for share in db.query(SalesAssetShare).filter_by(sales_asset_id=asset.id, revoked=False).all():
        revoke(db, share, user_id=user_id)


def invalidate_property_resources(db: Session, item, *, removed_source_id=None, remove_all=False, user_id=None) -> None:
    for asset in db.query(ProjectSalesAsset).filter_by(project_id=item.project_id, property_type_id=item.id).all():
        gallery = asset.source and asset.source.mime_type == GALLERY_MIME
        if not (remove_all or gallery or removed_source_id == asset.source_id):
            continue
        revoke_asset_links(db, asset, user_id=user_id)
        asset.approval_status = 'archived' if remove_all or not gallery else 'draft'
        asset.approved_at = None
        asset.approved_by_user_id = None
        db.add(asset)


def gallery_asset(db: Session, item) -> ProjectSalesAsset | None:
    return db.query(ProjectSalesAsset).join(ProjectOnboardingSource).filter(
        ProjectSalesAsset.project_id == item.project_id, ProjectSalesAsset.property_type_id == item.id,
        ProjectOnboardingSource.mime_type == GALLERY_MIME,
    ).first()


def save_gallery(db: Session, project, item, *, accessible: bool, channels: list[str], user_id: str):
    from . import sales_asset_service
    asset = gallery_asset(db, item)
    if not accessible:
        if asset:
            sales_asset_service.archive(db, asset, user_id=user_id)
        return asset
    if item.review_status != 'confirmed' or not item.media:
        raise HTTPException(422, 'Confirm this property type and attach at least one image before sharing its gallery.')
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             '<title>Property gallery</title><style>body{margin:auto;max-width:1100px;padding:24px;background:#0b0b0b;color:#fff;font:16px system-ui}img{max-width:100%;height:auto;border-radius:12px}figure{margin:24px 0}figcaption{padding:8px;color:#bbb}</style>',
             f'<h1>{escape(item.name)}</h1>']
    total = 0
    for media in sorted(item.media, key=lambda row: (row.sort_order, row.id)):
        source = media.source
        if not source or source.project_id != project.id or source.kind != ProjectSourceKind.IMAGE or source.status != ProjectSourceStatus.READY:
            raise HTTPException(422, 'Every gallery image must be a ready image from this Project.')
        content, mime, _ = read_resource(source)
        from .image_validation import validate_image
        try:
            validate_image(content, mime)
        except ValueError as exc:
            raise HTTPException(422, 'A selected image is invalid. Upload it again.') from exc
        total += len(content) * 4 // 3 + 1024
        if total > MAX_GALLERY_BYTES:
            raise HTTPException(422, 'The gallery is too large. Select fewer or smaller images (40 MB combined).')
        parts.append(f'<figure><img alt="{escape(media.caption or item.name, quote=True)}" src="data:{mime};base64,{base64.b64encode(content).decode()}"><figcaption>{escape(media.caption or item.name)}</figcaption></figure>')
    content = ''.join(parts).encode()
    digest = hashlib.sha256(content).hexdigest()
    if asset and asset.source.content_hash == digest and asset.allowed_channels == channels and available(asset):
        return asset
    if not asset or asset.source.content_hash != digest:
        source_id = str(uuid4())
        stored = storage_service.store_project_file(company_id=project.company_id, project_id=project.id, source_id=source_id,
            original_filename='property-gallery.html', content=content)
        source = ProjectOnboardingSource(id=source_id, project_id=project.id, uploaded_by_user_id=user_id,
            kind=ProjectSourceKind.UPLOADED_FILE, status=ProjectSourceStatus.READY, name=f'{item.name} gallery'[:255],
            original_filename='property-gallery.html', mime_type=GALLERY_MIME, size_bytes=len(content),
            storage_path=stored.relative_path, stored_filename=stored.stored_filename, is_encrypted=True,
            content_hash=stored.content_hash, encryption_key_id=stored.encryption_key_id,
            extracted_text='[User-approved gallery snapshot: selected property images only]', sharing_intent='internal')
        db.add(source); db.flush()
        if asset:
            revoke_asset_links(db, asset, user_id=user_id)
            asset.source = source; asset.source_id = source.id; asset.version += 1
        else:
            asset = ProjectSalesAsset(company_id=project.company_id,project_id=project.id,property_type_id=item.id,
                source_id=source.id,source=source,asset_type='gallery_image',content_tags=['gallery_image'],
                display_name=f'{item.name} gallery'[:255],created_by_user_id=user_id,approval_status='draft',version=1)
    else:
        revoke_asset_links(db, asset, user_id=user_id)
        asset.version += 1
    asset.allowed_channels = channels
    asset.display_name = f'{item.name} gallery'[:255]
    db.add(asset); db.flush()
    return sales_asset_service.approve(db, asset, user_id=user_id)
