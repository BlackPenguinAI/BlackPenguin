"""Public delivery traverses the production auth middleware without a user JWT."""
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from test_project_onboarding_block_b import uploads, attach_image, publish_gallery, upload_pdf
from app.core.middleware import MultiTenantMiddleware
from app.db.postgres import get_db
from app.modules.projects.router import router
from app.modules.projects import asset_share_service, services, sales_asset_service, storage_service
from app.modules.projects.models import ProjectSalesAsset, ProjectSourceStatus
from app.modules.projects.public_resource_page import GALLERY_SCRIPT, SCRIPT_HASH, render_gallery
from app.modules.sales_crm.models import Lead

@pytest.fixture
def anonymous(api):
    _, (db, *_) = api
    app = FastAPI()
    app.add_middleware(MultiTenantMiddleware)
    app.include_router(router, prefix='/api/v1/projects')
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client

def public_path(url):
    return urlsplit(url).path

def test_gallery_and_pdf_open_without_bearer_through_middleware(api, anonymous):
    editor, (_, _, _, project, _, item) = api
    attach_image(editor, project, item)
    gallery = publish_gallery(editor, project, item)
    pdf = upload_pdf(editor, project, item, True).json()
    page = anonymous.get(public_path(gallery['resource_url']))
    assert page.status_code == 200 and page.headers['content-type'].startswith('text/html')
    assert project.name in page.text and item.name in page.text and 'Available images' in page.text
    assert 'class="thumbnail"' in page.text and '<dialog' in page.text
    assert f"'sha256-{SCRIPT_HASH}'" in page.headers['content-security-policy']
    assert page.text.count('<script>') == 1 and GALLERY_SCRIPT in page.text
    result = anonymous.get(public_path(pdf['resource_url']))
    assert result.status_code == 200 and result.content.startswith(b'%PDF-')
    assert result.headers['content-type'] == 'application/pdf'
    assert result.headers['content-disposition'].startswith('inline;')
    assert result.headers['cache-control'] == 'no-store'

@pytest.mark.parametrize('method,suffix', [('POST',''),('PUT',''),('DELETE',''),('GET','/extra'),('GET','/extra/deeper')])
def test_public_bypass_never_opens_other_methods_or_nested_routes(anonymous, method, suffix):
    assert anonymous.request(method, '/api/v1/projects/resources/id/signature'+suffix).status_code == 401

def test_private_files_and_material_management_still_require_bearer(anonymous):
    for url in ['/api/v1/projects/id/sources/source/file', '/api/v1/projects/id/sales-assets']:
        assert anonymous.get(url).status_code == 401

@pytest.mark.parametrize('change', ['signature','unicode_signature','archive','expire','inactive','source_not_ready','remove_type','version'])
def test_unavailable_resources_fail_closed_with_friendly_page(api, anonymous, change):
    editor, (db, _, user, project, _, item) = api
    pdf = upload_pdf(editor, project, item, True).json()
    asset = db.get(ProjectSalesAsset, pdf['id'])
    url = public_path(pdf['resource_url'])
    if change == 'signature': url += 'x'
    elif change == 'unicode_signature': url = url.rsplit('/',1)[0]+'/á'
    elif change == 'archive': sales_asset_service.archive(db, asset, user_id=user.id)
    elif change == 'expire': asset.valid_until = datetime.utcnow()-timedelta(seconds=1)
    elif change == 'inactive': project.is_active = False
    elif change == 'source_not_ready': asset.source.status = ProjectSourceStatus.FAILED
    elif change == 'version': asset.version += 1
    else: assert editor.delete(f'/projects/{project.id}/property-types/{item.id}').status_code == 204
    db.commit()
    result = anonymous.get(url)
    assert result.status_code == 404 and result.headers['content-type'].startswith('text/html')
    assert 'This resource is no longer available.' in result.text
    assert result.headers['cache-control'] == 'no-store'
    assert 'Bearer' not in result.text and pdf['id'] not in result.text

def test_audited_lead_alias_uses_same_gallery_and_stops_after_revocation(api, anonymous):
    editor, (db, company, user, project, _, item) = api
    attach_image(editor, project, item)
    gallery = publish_gallery(editor, project, item)
    lead = Lead(company_id=company.id, project_id=project.id, full_name='Public recipient',phone='+15125550123')
    db.add(lead); db.commit()
    url, share = asset_share_service.issue(db, company_id=company.id,project_id=project.id,
        lead_id=lead.id, source_id=gallery['source_id'],sales_asset_id=gallery['id'],channel='whatsapp')
    direct = anonymous.get(public_path(gallery['resource_url']))
    delivered = anonymous.get(public_path(url), headers={'User-Agent':'Human browser'})
    assert delivered.status_code == 200 and delivered.content == direct.content
    db.refresh(share)
    assert share.access_count == 1 and share.first_human_access_at
    sales_asset_service.archive(db, db.get(ProjectSalesAsset, gallery['id']), user_id=user.id)
    for resource in (url, gallery['resource_url']):
        result = anonymous.get(public_path(resource))
        assert result.status_code == 404 and 'no longer available' in result.text

def test_overview_exposes_available_public_urls_and_normalizes_targeted_status(api):
    editor, (db, _, user, project, _, item) = api
    pdf = upload_pdf(editor, project, item, True).json()
    asset = db.get(ProjectSalesAsset, pdf['id'])
    asset.coverage = [{'property_type_id':item.id,'unit_id':None,'content_tags':['floor_plan'],'pages':[],'summary':''}]
    asset.approval_status = 'approved_targeted'
    db.commit()
    material = services.serialize_overview(db, project, user)['materials'][0]
    assert material['approval_status'] == 'approved' and material['resource_url']
    sales_asset_service.archive(db, asset, user_id=user.id)
    assert services.serialize_overview(db, project, user)['materials'][0]['resource_url'] is None

def test_existing_gallery_upgrades_without_reapproval_and_discards_source_scripts(api, anonymous):
    editor, (db, _, _, project, _, item) = api
    attach_image(editor, project, item)
    gallery = publish_gallery(editor, project, item)
    asset = db.get(ProjectSalesAsset, gallery['id'])
    stored = storage_service.read_project_file(asset.source.storage_path,encrypted=True)
    assert '<dialog' not in stored.decode()
    original = (asset.version, asset.approved_at, asset.source.content_hash)
    result = anonymous.get(public_path(gallery['resource_url']))
    assert result.status_code == 200 and '<dialog' in result.text
    assert (asset.version,asset.approved_at,asset.source.content_hash) == original
    rendered = render_gallery(stored+b'<script>alert("injected")</script><img src="https://private.test/leak">',
        project_name='<script>bad</script>', property_name='House')
    assert b'alert("injected")' not in rendered and b'private.test' not in rendered
    assert b'&lt;script&gt;bad&lt;/script&gt;' in rendered


def test_deleted_individual_unit_never_broadens_material_to_project_wide(api, anonymous):
    from app.modules.projects.models import ProjectUnit
    from app.modules.projects.property_resource_service import resource_url
    editor, (db, _, _, project, _, item) = api
    asset = db.get(ProjectSalesAsset, upload_pdf(editor, project, item, True).json()['id'])
    unit = ProjectUnit(project_id=project.id,unit_code='A101')
    db.add(unit); db.flush()
    asset.coverage = [{'property_type_id':None,'unit_id':unit.id,'content_tags':['floor_plan'],'pages':[],'summary':''}]
    asset.approval_status = 'approved_targeted'
    db.commit()
    url = resource_url(asset)
    assert anonymous.get(public_path(url)).status_code == 200
    db.delete(unit); db.commit()
    assert anonymous.get(public_path(url)).status_code == 404
    assert resource_url(asset) is None


def test_missing_or_tampered_file_gives_friendly_page(api, anonymous):
    editor, (db, _, _, project, _, item) = api
    document = upload_pdf(editor, project, item, True).json()
    asset = db.get(ProjectSalesAsset, document['id'])
    storage_service.resolve_project_file(asset.source.storage_path).write_bytes(b'corrupted bytes')
    result = anonymous.get(public_path(document['resource_url']))
    assert result.status_code == 404 and 'no longer available' in result.text


def test_pending_project_rename_does_not_change_published_gallery_title(api, anonymous):
    editor, (db, _, _, project, _, item) = api
    attach_image(editor, project, item)
    gallery = publish_gallery(editor, project, item)
    original_name = project.name
    project.name = 'Unapproved name'
    db.commit()
    result = anonymous.get(public_path(gallery['resource_url']))
    assert f'<h1>{original_name}</h1>' in result.text
    assert '<h1>Unapproved name</h1>' not in result.text
