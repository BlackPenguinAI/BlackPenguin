"""Additional acceptance cases, external to the repository under verification."""
import pytest
from copy import deepcopy
from app.modules.projects import catalog_service
from app.modules.projects.models import ProjectOnboardingSource, ProjectSalesAsset, ProjectMessage
from test_onboarding_ux_2325 import client, context, image_bytes


@pytest.mark.parametrize('mime,content',[
    ('image/png', b'\x89PNG\r\n\x1a\ntruncated'),
    ('image/jpeg', b'\xff\xd8\xfftruncated'),
    ('image/webp', b'RIFF\x04\x00\x00\x00WEBP'),
])
def test_truncated_image_with_valid_magic_is_not_ready_or_approvable(client,mime,content):
    api,(db,company,user,project,profile,item)=client
    response=api.post(f'/projects/{project.id}/sources/image-upload',
        files={'file':('broken-image',content,mime)},data={'sharing_intent':'sales_candidate'})
    asset=db.query(ProjectSalesAsset).first()
    approval_status=None
    if asset:
        approval=api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve')
        approval_status=approval.status_code
    sources=[{'status':source.status.value,'kind':source.kind.value} for source in db.query(ProjectOnboardingSource)]
    assert response.status_code==422, {'upload_status':response.status_code,'source_states':sources,'approval_http_status':approval_status}
    assert not asset or asset.approval_status!='approved'


@pytest.mark.parametrize('intent,expected_assets',[('internal',0),('sales_candidate',1)])
def test_real_png_does_not_gain_lead_permission_from_upload_and_attach(client,intent,expected_assets):
    api,(db,company,user,project,profile,item)=client
    response=api.post(f'/projects/{project.id}/sources/image-upload',
        files={'file':('valid.png',image_bytes(),'image/png')},data={'sharing_intent':intent})
    assert response.status_code==201
    source_id=response.json()['id']
    response=api.post(f'/projects/{project.id}/property-types/{item.id}/media',json={'source_ids':[source_id]})
    assert response.status_code==200
    assert db.query(ProjectSalesAsset).count()==expected_assets
    assert all(asset.approval_status=='draft' for asset in db.query(ProjectSalesAsset))


def test_property_history_stays_immutable_through_later_media_edit_and_removal(client):
    api,(db,company,user,project,profile,item)=client
    catalog_service.update(db,project,item,{'name':'First review','description':'Confirmed description'},user_id=user.id)
    receipt=db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type saved%')).one()
    initial=deepcopy(receipt.artifact_payload);original_text=receipt.content
    photo=api.post(f'/projects/{project.id}/sources/image-upload',files={'file':('photo.png',image_bytes(),'image/png')})
    assert photo.status_code==201
    attached=api.post(f'/projects/{project.id}/property-types/{item.id}/media',json={'source_ids':[photo.json()['id']]})
    assert attached.status_code==200
    catalog_service.update(db,project,item,{'name':'Second review','description':'New description'},user_id=user.id)
    catalog_service.remove(db,project,item,user_id=user.id)
    db.refresh(receipt)
    assert receipt.artifact_payload==initial and receipt.content==original_text
    assert initial['items'][0]['name']=='First review' and initial['items'][0]['media']==[]
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type images attached%')).count()==1
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type removed%')).count()==1
