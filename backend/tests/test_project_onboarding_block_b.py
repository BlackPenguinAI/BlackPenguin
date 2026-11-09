"""Block B: real file bytes, HTTP permissions, revisions and catalog continuity."""
from copy import deepcopy
from io import BytesIO
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from PIL import Image
from pypdf import PdfWriter
from unittest.mock import patch

from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects import services, asset_share_service, sales_asset_service
from app.modules.projects.models import Project, ProjectProfile, ProjectOnboardingSource, ProjectOnboardingProposal, ProjectProposalStatus, ProjectSalesAsset, ProjectSourceKind, ProjectSourceStatus, SenderType
from app.modules.projects.property_resource_service import GALLERY_MIME
from app.modules.sales_agent.material_delivery import snapshot
from app.modules.sales_crm.models import Lead
from app.modules.onboarding_questions import build_next_question


def path(url):
    return urlsplit(url).path.removeprefix('/api/v1')


def pdf_bytes():
    writer = PdfWriter(); writer.add_blank_page(width=200,height=200)
    out = BytesIO(); writer.write(out); return out.getvalue()


@pytest.fixture(autouse=True)
def uploads(tmp_path):
    with patch('app.core.config.settings.PROJECT_UPLOAD_ROOT',str(tmp_path)):
        yield


def attach_image(client, project, item, color='red'):
    out = BytesIO(); Image.new('RGB',(4,4),color).save(out,format='PNG')
    result = client.post(f'/projects/{project.id}/sources/image-upload',files={'file':('photo.png',out.getvalue(),'image/png')})
    assert result.status_code == 201,result.text
    source_id = result.json()['id']
    attached = client.post(f'/projects/{project.id}/property-types/{item.id}/media',json={'source_ids':[source_id]})
    assert attached.status_code == 200,attached.text
    return source_id


def publish_gallery(client, project, item, sources=None):
    payload = {'accessible_to_leads':True}
    if sources is not None: payload['source_ids'] = sources
    response = client.post(f'/projects/{project.id}/property-types/{item.id}/gallery',json=payload)
    assert response.status_code == 200,response.text
    return response.json()


def upload_pdf(client, project, item, shared=False, content=None, tags='["floor_plan","gallery_image"]'):
    return client.post(f'/projects/{project.id}/property-types/{item.id}/documents',
        files={'file':('plans.pdf',content if content is not None else pdf_bytes(),'application/pdf')},
        data={'accessible_to_leads':str(shared).lower(),'content_tags':tags})


@pytest.mark.parametrize('status',[ProjectProposalStatus.CONFIRMED,ProjectProposalStatus.CORRECTED])
def test_saved_proposal_can_be_revised_and_previous_publication_is_preserved(api,status):
    client,(db,company,user,project,profile,_) = api
    source = ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.URL,status=ProjectSourceStatus.READY,name='Website',url='https://example.com')
    db.add(source);db.flush()
    proposal = ProjectOnboardingProposal(source_id=source.id,field_key='project_name',value=project.name,status=status,revision=1,review_history=[{'action':'confirm','value':project.name}])
    db.add(proposal);db.commit()
    published = deepcopy(profile.published_snapshot)
    result = client.post(f'/projects/{project.id}/proposals/{proposal.id}/revision',json={'value':'Updated property project','expected_revision':1})
    assert result.status_code == 200,result.text
    assert result.json()['proposal']['status'] == 'corrected'
    assert result.json()['proposal']['revision'] == 2
    db.refresh(proposal);db.refresh(profile)
    assert proposal.review_history[0]['value'] == project.name
    assert len(proposal.review_history) == 2
    assert profile.profile_data['project_name'] == 'Updated property project'
    assert not profile.final_approved and profile.published_snapshot == published
    stale = client.post(f'/projects/{project.id}/proposals/{proposal.id}/revision',json={'value':'Stale update','expected_revision':1})
    assert stale.status_code == 409
    db.refresh(proposal)
    assert proposal.value == 'Updated property project' and proposal.revision == 2


@pytest.mark.parametrize('status',[ProjectProposalStatus.PENDING,ProjectProposalStatus.REJECTED])
def test_undecided_or_rejected_proposal_cannot_use_revision_endpoint(api,status):
    client,(db,_,_,project,_,_) = api
    source = ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.URL,status=ProjectSourceStatus.READY,name='Website')
    db.add(source);db.flush()
    proposal = ProjectOnboardingProposal(source_id=source.id,field_key='project_name',value='Old',status=status)
    db.add(proposal);db.commit()
    result = client.post(f'/projects/{project.id}/proposals/{proposal.id}/revision',json={'value':'New value'})
    assert result.status_code == 409


def test_gallery_is_one_scoped_link_with_selected_images_only(api):
    client,(db,_,_,project,_,item) = api
    source_id = attach_image(client,project,item)
    gallery = publish_gallery(client,project,item,[source_id])
    assert gallery['property_type_id'] == item.id and gallery['mime_type'] == GALLERY_MIME
    assert gallery['resource_url'] and gallery['approval_status'] == 'approved'
    response = client.get(path(gallery['resource_url']))
    assert response.status_code == 200,response.text
    assert response.headers['content-type'].startswith('text/html')
    assert response.text.count('<img ') == 1 and 'data:image/png;base64,' in response.text
    assert '/sources/' not in response.text and 'storage_path' not in response.text
    assert 'sandbox' in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    assert client.get(path(gallery['resource_url'])+'x').status_code == 404
    stored = db.get(ProjectSalesAsset,gallery['id'])
    assert snapshot(stored,channel='whatsapp')['content_sha256'] == stored.source.content_hash


def test_gallery_keeps_identity_updates_version_and_revokes_previous_links(api):
    client,(db,company,_,project,profile,item) = api
    first_image = attach_image(client,project,item)
    first = publish_gallery(client,project,item,[first_image])
    same = publish_gallery(client,project,item,[first_image])
    assert same['id'] == first['id'] and same['version'] == first['version'] and same['resource_url'] == first['resource_url']
    lead = Lead(company_id=company.id,project_id=project.id,full_name='Test lead',phone='+15125550001')
    db.add(lead);db.commit()
    link,share = asset_share_service.issue(db,company_id=company.id,project_id=project.id,lead_id=lead.id,source_id=first['source_id'],sales_asset_id=first['id'],channel='whatsapp')
    db.commit()
    assert client.get(path(link)).status_code == 200
    second_image = attach_image(client,project,item,'blue')
    assert client.get(path(first['resource_url'])).status_code == 404
    assert client.get(path(link)).status_code == 404
    db.refresh(share); assert share.revoked
    stale = client.post(f'/projects/{project.id}/property-types/{item.id}/gallery',json={'accessible_to_leads':True,'source_ids':[first_image]})
    assert stale.status_code == 409
    second = publish_gallery(client,project,item,[first_image,second_image])
    assert second['id'] == first['id'] and second['version'] > first['version']
    assert second['resource_url'] != first['resource_url']
    assert client.get(path(second['resource_url'])).text.count('<img ') == 2
    response = client.delete(f'/projects/{project.id}/property-types/{item.id}/media/{first_image}')
    assert response.status_code == 200,response.text
    assert client.get(path(second['resource_url'])).status_code == 404
    updated = publish_gallery(client,project,item,[second_image])
    assert updated['id'] == first['id']
    assert client.get(path(updated['resource_url'])).text.count('<img ') == 1


def test_gallery_opt_out_and_property_removal_revoke_access(api):
    client,(db,_,_,project,_,item) = api
    attach_image(client,project,item)
    gallery = publish_gallery(client,project,item)
    response = client.post(f'/projects/{project.id}/property-types/{item.id}/gallery',json={'accessible_to_leads':False})
    assert response.status_code == 200 and response.json()['resource_url'] is None
    assert client.get(path(gallery['resource_url'])).status_code == 404
    gallery = publish_gallery(client,project,item)
    assert client.delete(f'/projects/{project.id}/property-types/{item.id}').status_code == 204
    assert client.get(path(gallery['resource_url'])).status_code == 404


def test_adding_images_marks_only_draft_and_preserves_published_media(api):
    client,(db,_,_,project,profile,item) = api
    published = deepcopy(profile.published_snapshot)
    attach_image(client,project,item)
    db.refresh(profile)
    assert profile.published_snapshot == published
    assert not profile.final_approved
    assert profile.field_states['target_audience']['status'] == 'confirmed'


def test_removing_last_image_is_idempotent_and_retains_source(api):
    client,(db,_,_,project,_,item) = api
    image_id = attach_image(client,project,item)
    for _ in range(2):
        response = client.delete(f'/projects/{project.id}/property-types/{item.id}/media/{image_id}')
        assert response.status_code == 200,response.text
        assert response.json()['media'] == []
    assert db.get(ProjectOnboardingSource,image_id) is not None


def test_pdf_is_internal_by_default_then_explicitly_shareable_and_revocable(api):
    client,(db,company,_,project,_,item) = api
    response = upload_pdf(client,project,item)
    assert response.status_code == 201,response.text
    asset = response.json()
    assert asset['property_type_id'] == item.id and asset['approval_status'] == 'archived'
    assert asset['resource_url'] is None
    approved = client.post(f'/projects/{project.id}/sales-assets/{asset["id"]}/approve')
    assert approved.status_code == 200,approved.text
    url = approved.json()['resource_url']
    assert client.get(path(url)).content == pdf_bytes()
    assert client.get(path(url)).headers['content-type'].startswith('application/pdf')
    assert client.delete(f'/projects/{project.id}/sales-assets/{asset["id"]}').status_code == 204
    assert client.get(path(url)).status_code == 404


def test_pdf_multi_content_and_removal_preserve_onboarding_facts(api):
    client,(db,_,_,project,profile,item) = api
    before = deepcopy(profile.profile_data)
    uploaded = upload_pdf(client,project,item,True)
    assert uploaded.status_code == 201,uploaded.text
    asset = uploaded.json()
    assert asset['content_tags'] == ['floor_plan','gallery_image']
    assert client.get(path(asset['resource_url'])).status_code == 200
    assert profile.profile_data == before
    response = client.delete(f'/projects/{project.id}/property-types/{item.id}/documents/{asset["id"]}')
    assert response.status_code == 204,response.text
    assert client.get(path(asset['resource_url'])).status_code == 404
    db.refresh(profile)
    assert profile.profile_data == before
    stored = db.get(ProjectSalesAsset,asset['id'])
    assert stored.property_type_id is None and stored.approval_status == 'archived'


@pytest.mark.parametrize('content,tags',[(b'%PDF-not-a-document','["floor_plan"]'),(b'not pdf','[]'),(None,'["invalid"]')])
def test_invalid_pdf_or_classification_does_not_create_resource(api,content,tags):
    client,(db,_,_,project,_,item) = api
    count = db.query(ProjectSalesAsset).count()
    response = upload_pdf(client,project,item,True,content,tags)
    assert response.status_code == 422
    assert db.query(ProjectSalesAsset).count() == count


def test_resource_links_cannot_cross_property_or_company(api):
    client,(db,company,user,project,_,item) = api
    document = upload_pdf(client,project,item,True).json()
    other = Project(company_id=company.id,name='Other project');db.add(other);db.commit()
    assert client.delete(f'/projects/{other.id}/property-types/{item.id}/documents/{document["id"]}').status_code == 404
    assert client.post(f'/projects/{other.id}/property-types/{item.id}/gallery',json={'accessible_to_leads':True}).status_code == 404
    assert client.get(path(document['resource_url']).replace(document['id'],str(uuid4()))).status_code == 404


def test_catalog_updates_do_not_consume_another_active_question(api):
    client,(db,_,_,project,profile,item) = api
    services.apply_field_updates(db,profile,[{'field':'target_audience','value':None,'status':'missing'}],allow_authoritative_statuses=True)
    ui = build_next_question([{'field':'target_audience','label':'Target audience','requirement':'required'}],final_prompt='Review')
    question = services.save_message(db,project.session.id,SenderType.AI,'Audience?',ui_payload=ui)
    response = client.put(f'/projects/{project.id}/property-types/{item.id}',json={'name':item.name,'description':'Reviewed by administrator','starting_price':30,'maximum_price':45.75,'currency':'USD','available_units':3})
    assert response.status_code == 200,response.text
    assert client.post(f'/projects/{project.id}/property-types/confirm').status_code == 200
    state = client.get(f'/projects/{project.id}/chat/state')
    assert state.status_code == 200,state.text
    db.refresh(question)
    assert question.response_payload is None
    assert state.json()['next_question']['field'] == 'target_audience'


def test_gallery_escapes_property_names_and_detects_changed_file_bytes(api):
    from app.modules.projects import storage_service
    client,(db,_,_,project,_,item) = api
    item.name = '<script>alert("not executable")</script>';db.commit()
    attach_image(client,project,item)
    asset = publish_gallery(client,project,item)
    response = client.get(path(asset['resource_url']))
    assert response.status_code == 200
    assert '<script>' not in response.text and '&lt;script&gt;' in response.text
    source = db.get(ProjectSalesAsset,asset['id']).source
    storage_service.resolve_project_file(source.storage_path).write_bytes(b'changed encrypted bytes')
    assert client.get(path(asset['resource_url'])).status_code == 404


def test_other_company_cannot_change_document_or_gallery_permissions(api):
    from app.modules.companies.models import Company
    from app.modules.users.models import User,UserRole
    from app.modules.auth.deps import get_current_user
    client,(db,_,_,project,_,item) = api
    asset = upload_pdf(client,project,item,True).json()
    other = Company(name='Other Company',country_code='US');db.add(other);db.flush()
    user = User(company_id=other.id,email='other@resources.test',hashed_password='unused',role=UserRole.ADMIN,is_active=True)
    db.add(user);db.commit()
    client.app.dependency_overrides[get_current_user] = lambda:user
    assert upload_pdf(client,project,item).status_code == 404
    assert client.delete(f'/projects/{project.id}/property-types/{item.id}/documents/{asset["id"]}').status_code == 404
    assert client.post(f'/projects/{project.id}/property-types/{item.id}/gallery',json={'accessible_to_leads':False}).status_code == 404
    assert client.get(path(asset['resource_url'])).status_code == 200  # Only the authorized capability remains public.


def test_sales_role_cannot_upload_or_publish_property_resources(api):
    from app.modules.users.models import UserRole
    client,(db,_,user,project,_,item) = api
    user.role = UserRole.SALES;db.commit()
    assert upload_pdf(client,project,item).status_code == 403
    assert client.post(f'/projects/{project.id}/property-types/{item.id}/gallery',json={'accessible_to_leads':True}).status_code == 403


def test_link_revocation_records_the_current_actor_not_the_original_approver(api):
    from app.modules.users.models import User,UserRole
    from app.modules.auth.deps import get_current_user
    client,(db,company,publisher,project,_,item) = api
    document = upload_pdf(client,project,item,True).json()
    lead = Lead(company_id=company.id,project_id=project.id,full_name='Recipient',phone='+15125550002')
    db.add(lead);db.commit()
    _,share = asset_share_service.issue(db,company_id=company.id,project_id=project.id,lead_id=lead.id,
        source_id=document['source_id'],sales_asset_id=document['id'],channel='whatsapp')
    operator = User(company_id=company.id,email='operator@resources.test',hashed_password='unused',role=UserRole.ADMIN,is_active=True)
    db.add(operator);db.commit()
    client.app.dependency_overrides[get_current_user] = lambda:operator
    response = client.delete(f'/projects/{project.id}/sales-assets/{document["id"]}')
    assert response.status_code == 204,response.text
    db.refresh(share)
    assert share.revoked and share.revoked_by_user_id == operator.id
    assert share.revoked_by_user_id != publisher.id
