from io import BytesIO
from unittest.mock import patch
import pytest
from PIL import Image
from app.modules.projects import image_validation, sales_asset_service, storage_service
from app.modules.projects.image_validation import validate_image
from app.modules.projects.models import ProjectOnboardingSource, ProjectSourceKind, ProjectSourceStatus, ProjectSalesAsset, ProjectMessage
from test_onboarding_ux_2325 import client, context


def encoded(fmt='PNG'):
    output=BytesIO();Image.new('RGB',(12,10),'blue').save(output,format=fmt);return output.getvalue()


@pytest.mark.parametrize('fmt,mime',[('PNG','image/png'),('JPEG','image/jpeg'),('WEBP','image/webp')])
def test_valid_images_decode_and_original_bytes_are_preserved(client,fmt,mime):
    api,(db,company,user,project,profile,item)=client
    content=encoded(fmt)
    response=api.post(f'/projects/{project.id}/sources/image-upload',files={'file':('photo',content,mime)},data={'sharing_intent':'sales_candidate'})
    assert response.status_code==201,response.text
    source=db.query(ProjectOnboardingSource).filter_by(id=response.json()['id']).one()
    assert storage_service.read_project_file(source.storage_path,encrypted=True)==content
    asset=db.query(ProjectSalesAsset).one();assert asset.approval_status=='draft'
    assert api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve').status_code==200
    assert asset.approval_status=='approved'


@pytest.mark.parametrize('fmt,mime',[('PNG','image/png'),('JPEG','image/jpeg'),('WEBP','image/webp')])
def test_images_with_valid_headers_but_truncated_payload_are_rejected(fmt,mime):
    content=encoded(fmt)
    with pytest.raises(ValueError):validate_image(content[:max(16,len(content)//2)],mime)


@pytest.mark.parametrize('mime',['image/jpeg','image/webp','image/svg+xml'])
def test_mime_mismatch_or_unapproved_format_is_rejected(mime):
    with pytest.raises(ValueError):validate_image(encoded('PNG'),mime)


def test_pixel_limit_rejects_before_pixel_allocation(monkeypatch):
    content=encoded();monkeypatch.setattr(image_validation,'MAX_IMAGE_PIXELS',100)
    with patch.object(Image.Image,'load',side_effect=AssertionError('Must reject before decoding')):
        with pytest.raises(ValueError,match='dimensions'):validate_image(content,'image/png')


@pytest.mark.parametrize('limit_name,limit',[('MAX_IMAGE_FRAMES',1),('MAX_TOTAL_FRAME_PIXELS',100)])
@pytest.mark.parametrize('fmt,mime',[('WEBP','image/webp'),('PNG','image/png')])
def test_multiframe_images_are_decoded_with_bounded_work(monkeypatch,limit_name,limit,fmt,mime):
    output=BytesIO();first=Image.new('RGB',(10,10),'blue');second=Image.new('RGB',(10,10),'red')
    first.save(output,format=fmt,save_all=True,append_images=[second],duration=100,loop=0)
    validate_image(output.getvalue(),mime)
    monkeypatch.setattr(image_validation,limit_name,limit)
    with pytest.raises(ValueError,match='too many frames|too large'):validate_image(output.getvalue(),mime)


def legacy_image(case,content):
    db,company,user,project,profile,item=case
    source=ProjectOnboardingSource(project_id=project.id,uploaded_by_user_id=user.id,kind=ProjectSourceKind.IMAGE,
        status=ProjectSourceStatus.READY,name='Legacy image',mime_type='image/png',size_bytes=len(content),sharing_intent='sales_candidate',intended_asset_type='gallery_image')
    db.add(source);db.flush()
    stored=storage_service.store_project_file(company_id=company.id,project_id=project.id,source_id=source.id,original_filename='legacy.png',content=content)
    source.storage_path=stored.relative_path;source.is_encrypted=True;db.add(source)
    asset=sales_asset_service.materialize_source_candidate(db,source);db.commit();return source,asset


def test_legacy_ready_but_corrupt_image_cannot_be_approved_or_erase_history(client):
    api,case=client;db,company,user,project,profile,item=case
    source,asset=legacy_image(case,b'\x89PNG\r\n\x1a\ntruncated')
    old_count=db.query(ProjectMessage).count()
    response=api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve')
    assert response.status_code==422 and 'cannot be approved' in response.json()['detail']
    assert asset.approval_status=='draft' and asset.approved_at is None
    assert source.status==ProjectSourceStatus.READY and db.query(ProjectMessage).count()==old_count
    assert storage_service.read_project_file(source.storage_path,encrypted=True).endswith(b'truncated')


def test_legacy_ready_valid_image_can_still_be_approved(client):
    api,case=client;db,company,user,project,profile,item=case
    source,asset=legacy_image(case,encoded())
    assert api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve').status_code==200
    assert asset.approval_status=='approved'


def test_missing_stored_image_yields_readable_error_without_server_paths(client):
    api,case=client;db,company,user,project,profile,item=case
    source,asset=legacy_image(case,encoded());source.storage_path='missing/image.png';db.commit()
    response=api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve')
    assert response.status_code==422 and 'cannot be approved' in response.json()['detail']
    assert 'missing/image.png' not in response.json()['detail'] and asset.approval_status=='draft'


def test_legacy_image_with_missing_mime_cannot_bypass_validation(client):
    api,case=client;db,company,user,project,profile,item=case
    source,asset=legacy_image(case,b'broken');source.mime_type=None;db.commit()
    assert api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve').status_code==422
    assert asset.approval_status=='draft'
