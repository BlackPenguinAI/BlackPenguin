"""Issues 23–25: real API/storage/DB paths; no model or provider calls."""
from copy import deepcopy
import base64
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user
from app.modules.onboarding_deferrals import Decision, save, records, question_blockers, router as deferrals_router
from app.modules.projects import catalog_service, storage_service
from app.modules.projects.router import router
from app.modules.projects.models import ProjectMessage, ProjectOnboardingSource, ProjectSalesAsset
from app.modules.users.models import UserRole
from test_onboarding_revisions_and_money import context


@pytest.fixture
def client(context, tmp_path, monkeypatch):
    db, company, user, project, profile, item = context
    monkeypatch.setattr(storage_service.settings, 'PROJECT_UPLOAD_ROOT', str(tmp_path))
    app=FastAPI();app.include_router(router,prefix='/projects');app.include_router(deferrals_router,prefix='/deferrals')
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:user
    with TestClient(app) as api:
        yield api,context


def image_bytes():
    return base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def upload(api,project,**data):
    return api.post(f'/projects/{project.id}/sources/image-upload',files={'file':('own.png',image_bytes(),'image/png')},data=data)


def test_resume_prioritizes_requested_required_field(context):
    db,company,user,project,profile,item=context
    save(db,profile,'project',project.id,Decision(card='field:city',draft={'answer':'Lima'}),user)
    save(db,profile,'project',project.id,Decision(card='field:city',resume=True),user)
    blockers=[{'field':'country'},{'field':'city'}]
    assert question_blockers(profile,blockers)[0]['field']=='city'
    assert records(profile)['field:city']['draft']=={'answer':'Lima'}


def test_deferred_snapshot_survives_resume_and_save(context):
    db,company,user,project,profile,item=context
    draft={'name':'Unapproved draft','starting_price':999}
    save(db,profile,'project',project.id,Decision(card='property:'+item.id,draft=draft),user)
    receipt=db.query(ProjectMessage).filter(ProjectMessage.content.like('Configured for later%')).one()
    snapshot=deepcopy(receipt.response_payload)
    save(db,profile,'project',project.id,Decision(card='property:'+item.id,resume=True),user)
    catalog_service.update(db,project,item,{'name':'New approved name'},user_id=user.id)
    db.refresh(receipt)
    assert receipt.response_payload==snapshot
    assert snapshot['draft_snapshot']==draft and snapshot['actor_user_id']==user.id
    assert item.starting_price==30


def test_property_receipts_preserve_old_values_after_edit_and_removal(context):
    db,company,user,project,profile,item=context
    catalog_service.update(db,project,item,{'name':'First change'},user_id=user.id)
    receipt=db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type saved%')).one()
    snapshot=deepcopy(receipt.artifact_payload)
    catalog_service.update(db,project,item,{'name':'Second change'},user_id=user.id)
    catalog_service.remove(db,project,item,user_id=user.id)
    db.refresh(receipt)
    assert receipt.artifact_payload==snapshot
    assert snapshot['items'][0]['name']=='First change'
    removed=db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type removed%')).one()
    assert removed.artifact_payload['items'][0]['name']=='Second change'
    assert removed.artifact_payload['actor_user_id']==user.id


@pytest.mark.parametrize('sharing,asset_count',[('internal',0),('sales_candidate',1)])
def test_image_upload_is_ready_without_implicit_approval_or_cover(client,sharing,asset_count):
    api,(db,company,user,project,profile,item)=client
    published=deepcopy(profile.published_snapshot)
    response=upload(api,project,sharing_intent=sharing,content_tags='["gallery_image","floor_plan"]')
    assert response.status_code==201,response.text
    source=db.query(ProjectOnboardingSource).filter_by(id=response.json()['id']).one()
    assert source.status.value=='ready' and not source.is_primary
    assert source.sharing_intent==sharing and source.intended_content_tags==['gallery_image','floor_plan']
    assert db.query(ProjectSalesAsset).count()==asset_count
    if asset_count:
        asset=db.query(ProjectSalesAsset).one()
        assert asset.approval_status=='draft' and asset.approved_at is None
    assert profile.published_snapshot==published
    attached=api.post(f'/projects/{project.id}/property-types/{item.id}/media',json={'source_ids':[source.id]})
    assert attached.status_code==200,attached.text
    assert len(attached.json()['media'])==1
    assert item.name=='Residence A' and item.starting_price==30
    # Idempotent association does not duplicate images or history receipts.
    api.post(f'/projects/{project.id}/property-types/{item.id}/media',json={'source_ids':[source.id]})
    assert len(item.media)==1
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type images attached%')).count()==1
    assert all(asset.approval_status=='draft' for asset in db.query(ProjectSalesAsset))
    from app.modules.projects.services import serialize_overview
    overview=serialize_overview(db,project,user)
    assert any(f'/sources/{source.id}/file' in url for unit in overview['inventory'] for url in unit['images'])


@pytest.mark.parametrize('tags',['[]','null','{}','["unsupported"]','[["gallery_image"]]','not json'])
def test_invalid_image_classification_is_readable_and_does_not_store(client,tags):
    api,(db,company,user,project,profile,item)=client
    response=upload(api,project,content_tags=tags)
    assert response.status_code==422 and isinstance(response.json()['detail'],str)
    assert db.query(ProjectOnboardingSource).count()==0


@pytest.mark.parametrize('mime,content',[('image/png',b'not an image'),('image/svg+xml',b'<svg/>'),('application/pdf',b'%PDF-')])
def test_invalid_image_upload_is_never_ready_or_approved(client,mime,content):
    api,(db,company,user,project,profile,item)=client
    response=api.post(f'/projects/{project.id}/sources/image-upload',files={'file':('fake',content,mime)})
    assert response.status_code==422
    assert db.query(ProjectSalesAsset).count()==0
    assert all(source.status.value=='failed' for source in db.query(ProjectOnboardingSource))


def test_image_size_is_enforced_on_server(client):
    api,(db,company,user,project,profile,item)=client
    with patch('app.modules.projects.source_service.MAX_FILE_BYTES',8):
        response=upload(api,project)
    assert response.status_code==422 and 'limit' in response.json()['detail']
    assert db.query(ProjectSalesAsset).count()==0


def test_foreign_project_upload_is_denied(client):
    api,(db,company,user,project,profile,item)=client
    response=api.post('/projects/foreign/sources/image-upload',files={'file':('photo.png',image_bytes(),'image/png')})
    assert response.status_code==404 and db.query(ProjectOnboardingSource).count()==0


def test_selected_project_scope_is_enforced_for_upload_and_draft(client):
    api,(db,company,user,project,profile,item)=client
    user.role=UserRole.ASSISTANT;user.project_access_scope='selected';db.commit()
    assert upload(api,project).status_code==404
    assert api.post(f'/deferrals/project/{project.id}',json={'card':'property:'+item.id}).status_code==404
    assert not records(profile)


def test_each_material_can_be_deferred_and_resumed_independently(client):
    api,(db,company,user,project,profile,item)=client
    upload(api,project,sharing_intent='sales_candidate')
    asset=db.query(ProjectSalesAsset).one()
    response=api.post(f'/deferrals/project/{project.id}',json={'card':'material:'+asset.id,'draft':{'display_name':asset.display_name}})
    assert response.status_code==200 and records(profile)['material:'+asset.id]['deferred']
    assert asset.approval_status=='draft' and not records(profile).get('materials')
    assert api.post(f'/deferrals/project/{project.id}',json={'card':'material:foreign'}).status_code==404
    api.post(f'/deferrals/project/{project.id}',json={'card':'material:'+asset.id,'resume':True})
    assert api.post(f'/projects/{project.id}/sales-assets/{asset.id}/approve').status_code==200
    assert not records(profile)['material:'+asset.id]['resumed']
    assert records(profile)['material:'+asset.id]['draft']=={}
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Configured for later%')).one().response_payload['draft_snapshot']['display_name']==asset.display_name


def test_saving_new_type_does_not_resurrect_full_catalog_new_draft(context):
    db,company,user,project,profile,item=context
    save(db,profile,'project',project.id,Decision(card='field:property_type_catalog',draft={'newType':{'name':'Pending new','selected_images':['old']},'items':[{'id':item.id,'name':'Keep pending'}]}),user)
    catalog_service.create(db,project,{'name':'New type','review_status':'confirmed'},user_id=user.id)
    assert 'newType' not in records(profile)['field:property_type_catalog']['draft']
    assert records(profile)['field:property_type_catalog']['draft']['items'][0]['name']=='Keep pending'


@pytest.mark.parametrize('role',[UserRole.SALES])
def test_image_upload_requires_editor_role(client,role):
    api,(db,company,user,project,profile,item)=client
    user.role=role;db.commit()
    assert upload(api,project).status_code==403


def test_marketing_editor_keeps_existing_project_edit_permission(client):
    api,(db,company,user,project,profile,item)=client
    user.role=UserRole.MKT;db.commit()
    assert upload(api,project).status_code==201


def test_postpone_images_keeps_fields_and_history_without_duplicate_receipt(client):
    api,(db,company,user,project,profile,item)=client
    for _ in range(2):
        assert api.post(f'/projects/{project.id}/property-types/{item.id}/defer-images').status_code==200
    assert item.images_status=='deferred' and item.starting_price==30
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Property type images configured for later%')).count()==1
