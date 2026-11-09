"""Block A HTTP regressions against an isolated DB; no providers or models."""
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects import services
from app.modules.projects.editor_tasks import detect_task
from app.modules.projects.models import Project, ProjectMessage, ProjectOnboardingSource, ProjectSession, SenderType
from app.modules.onboarding_jobs.models import OnboardingSourceJob
from app.modules.onboarding_questions import build_next_question
from app.modules.governance.models import PlatformAuditEvent

AUDIENCE = 'Buyers seeking a master-planned community in Virginia Beach, Virginia, with practical layouts, a defined purchase timeline, and readiness to evaluate available inventory.'

def question(db, project, blockers=None):
    services.supersede_unanswered_questions(db, project.session.id)
    payload = build_next_question(blockers or [], final_prompt='Review the profile')
    return services.save_message(db, project.session.id, SenderType.AI, payload['prompt'], ui_payload=payload)

def test_inventory_in_audience_is_not_navigation():
    assert detect_task(AUDIENCE) is None
    assert detect_task("Okay, let's fill in available inventory") == 'catalog'

@pytest.mark.parametrize('bound', [False, True])
def test_audience_advances_and_preserves_catalog(api, bound):
    client, (db, _, _, project, profile, _) = api
    original_catalog = deepcopy(profile.field_states['property_type_catalog'])
    q = question(db, project, [{'field':'target_audience','label':'Target audience','requirement':'required'}])
    body = {'message':AUDIENCE, 'client_message_id':str(uuid4())}
    if bound: body['in_reply_to_message_id'] = q.id
    with patch('app.modules.projects.router.generate_llm_response', side_effect=AssertionError('No model needed')):
        response = client.post(f'/projects/{project.id}/chat', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['profile']['data']['target_audience'] == AUDIENCE
    assert response.json()['next_question']['field'] != 'property_type_catalog'
    db.refresh(q)
    assert q.response_payload['status'] == 'accepted'
    assert profile.field_states['property_type_catalog'] == original_catalog

def test_bound_answer_with_edit_words_remains_an_answer(api):
    client, (db, _, _, project, _, _) = api
    q = question(db, project, [{'field':'target_audience','label':'Target audience','requirement':'required'}])
    text = 'I want to update property buyers with practical layouts and convenient access to everyday services.'
    response = client.post(f'/projects/{project.id}/chat', json={'message':text,'in_reply_to_message_id':q.id,'client_message_id':str(uuid4())})
    assert response.status_code == 200, response.text
    assert response.json()['profile']['data']['target_audience'] == text
    assert not response.json()['next_question'].get('task')

@pytest.mark.parametrize('bound', [False, True])
def test_text_approval_and_replay_redirect_once(api, bound):
    client, (db, _, user, project, profile, _) = api
    services.apply_field_updates(db, profile, [services.user_field_update('target_audience',AUDIENCE)], allow_authoritative_statuses=True, actor_user_id=user.id)
    q = question(db, project)
    body = {'message':'Approve profile','client_message_id':str(uuid4())}
    if bound: body['in_reply_to_message_id'] = q.id
    before = db.query(PlatformAuditEvent).filter_by(event_type='onboarding.profile_approved').count()
    for _ in range(2):
        response = client.post(f'/projects/{project.id}/chat', json=body)
        assert response.status_code == 200, response.text
        assert response.json()['redirect_url'] == f'/app/projects/{project.id}'
    db.refresh(q); db.refresh(project); db.refresh(profile)
    assert q.response_payload['status'] == 'accepted'
    assert project.onboarding_status == 'completed' and profile.final_approved
    assert db.query(PlatformAuditEvent).filter_by(event_type='onboarding.profile_approved').count() == before + 1
    assert db.query(ProjectMessage).filter_by(id=body['client_message_id']).count() == 1

def test_explicit_completion_records_answer_without_republication(api):
    client, (db, _, user, project, profile, _) = api
    services.apply_field_updates(db, profile, [services.user_field_update('target_audience',AUDIENCE)], allow_authoritative_statuses=True, actor_user_id=user.id)
    q = question(db, project)
    first = client.post(f'/projects/{project.id}/onboarding/complete')
    assert first.status_code == 200, first.text
    second = client.post(f'/projects/{project.id}/onboarding/complete')
    assert second.status_code == 200, second.text
    assert second.json()['redirect_url'] == f'/app/projects/{project.id}'
    assert first.json()['profile']['completion']['published_revision'] == second.json()['profile']['completion']['published_revision']
    db.refresh(q)
    assert q.response_payload['selected_option'] == 'Approve profile'

def test_blocked_approval_keeps_question_unanswered(api):
    client, (db, _, user, project, profile, _) = api
    services.apply_field_updates(db, profile, [{'field':'target_audience','value':None,'status':'missing'}], allow_authoritative_statuses=True, actor_user_id=user.id)
    q = question(db, project)
    published = deepcopy(profile.published_snapshot)
    response = client.post(f'/projects/{project.id}/onboarding/complete')
    assert response.status_code == 409, response.text
    db.refresh(q); db.refresh(profile)
    assert q.response_payload is None and not profile.final_approved
    assert profile.published_snapshot == published

@pytest.mark.parametrize('website', [None,'https://example.com/homes'])
@pytest.mark.parametrize('autoflush', [False, True])
def test_start_and_retry_create_one_project_and_initial_turn(api, website, autoflush):
    client, (db, _, _, _, _, _) = api
    db.autoflush = autoflush
    before = db.query(Project).count()
    body = {'client_request_id':str(uuid4()),'initial_url':website,'skip_website':website is None}
    with patch('app.modules.projects.router.services.check_project_limits') as limit, patch('app.modules.projects.source_service.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]):
        first = client.post('/projects/start',json=body)
        assert first.status_code == 201, first.text
        second = client.post('/projects/start',json=body)
        assert second.status_code == 201, second.text
    assert first.json()['id'] == second.json()['id']
    assert db.query(Project).count() == before+1 and limit.call_count == 1
    project = db.get(Project,first.json()['id'])
    assert project.onboarding_status == 'in_progress'
    assert db.query(ProjectMessage).filter_by(session_id=project.session.id).count() == (2 if website else 1)
    assert db.query(ProjectOnboardingSource).filter_by(project_id=project.id).count() == int(bool(website))
    assert db.query(OnboardingSourceJob).filter_by(project_id=project.id).count() == int(bool(website))

@pytest.mark.parametrize('choice',[{}, {'initial_url':'not-a-url'}, {'initial_url':'https://example.com','skip_website':True}, {'initial_url':'ftp://example.com'}])
def test_invalid_start_creates_nothing(api,choice):
    client,(db,*_) = api
    before = db.query(Project).count()
    response = client.post('/projects/start',json={'client_request_id':str(uuid4()),**choice})
    assert response.status_code == 422
    assert db.query(Project).count() == before

def test_failed_bootstrap_rolls_back_creation_then_retry_succeeds(api):
    client,(db,*_) = api
    before = db.query(Project).count(); sessions = db.query(ProjectSession).count()
    body = {'client_request_id':str(uuid4()),'skip_website':True}
    with patch('app.modules.projects.router.services.check_project_limits'), patch('app.modules.projects.router.start_chat',side_effect=HTTPException(503,'Try again')):
        failed = client.post('/projects/start',json=body)
    assert failed.status_code == 503
    assert db.query(Project).count() == before and db.query(ProjectSession).count() == sessions
    with patch('app.modules.projects.router.services.check_project_limits'):
        retry = client.post('/projects/start',json=body)
    assert retry.status_code == 201, retry.text
    assert db.query(Project).count() == before+1

def test_start_key_cannot_change_choice(api):
    client,(db,*_) = api
    body = {'client_request_id':str(uuid4()),'skip_website':True}
    with patch('app.modules.projects.router.services.check_project_limits'):
        assert client.post('/projects/start',json=body).status_code == 201
    before = db.query(Project).count()
    response = client.post('/projects/start',json={**body,'skip_website':False,'initial_url':'https://example.com'})
    assert response.status_code == 409 and db.query(Project).count() == before

def test_legacy_draft_endpoint_remains_available(api):
    client,(db,*_) = api
    with patch('app.modules.projects.router.services.check_project_limits'):
        response = client.post('/projects/drafts',json={})
    assert response.status_code == 201, response.text
    assert db.get(Project,response.json()['id']).onboarding_status == 'draft'


def test_company_limit_rejection_creates_nothing(api):
    client,(db,*_) = api
    before = db.query(Project).count()
    with patch('app.modules.projects.router.services.check_project_limits', side_effect=HTTPException(403,'Project limit reached')):
        response = client.post('/projects/start',json={'client_request_id':str(uuid4()),'skip_website':True})
    assert response.status_code == 403
    assert db.query(Project).count() == before


def test_private_url_rejection_does_not_leave_a_draft(api):
    client,(db,*_) = api
    before = db.query(Project).count()
    with patch('app.modules.projects.router.services.check_project_limits'), patch('app.modules.projects.source_service.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
        response = client.post('/projects/start',json={'client_request_id':str(uuid4()),'initial_url':'https://localhost/homes'})
    assert response.status_code == 400, response.text
    assert db.query(Project).count() == before


def test_retry_key_is_scoped_to_authenticated_company_and_actor(api):
    from app.modules.companies.models import Company
    from app.modules.users.models import User, UserRole
    from app.modules.auth.deps import get_current_user
    client,(db,*_) = api
    body = {'client_request_id':str(uuid4()),'skip_website':True}
    with patch('app.modules.projects.router.services.check_project_limits'):
        first = client.post('/projects/start',json=body)
        other_company = Company(name='Other tenant',country_code='US')
        db.add(other_company); db.flush()
        other_user = User(company_id=other_company.id,email='other@start.test',hashed_password='unused',role=UserRole.ADMIN,is_active=True)
        db.add(other_user); db.commit()
        client.app.dependency_overrides[get_current_user] = lambda: other_user
        second = client.post('/projects/start',json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()['id'] != second.json()['id']
    assert db.get(Project,second.json()['id']).company_id == other_company.id


def test_sales_role_cannot_start_projects(api):
    from app.modules.users.models import UserRole
    client,(db,_,user,*_) = api
    user.role = UserRole.SALES; db.commit()
    before = db.query(Project).count()
    response = client.post('/projects/start',json={'client_request_id':str(uuid4()),'skip_website':True})
    assert response.status_code == 403
    assert db.query(Project).count() == before


def test_approval_with_deferred_operations_does_not_activate_sales(api):
    client,(db,_,user,project,profile,_) = api
    services.apply_field_updates(db,profile,[services.user_field_update(field,False,status='deferred') for field in ['campaigns_defined','meta_connection_verified']],allow_authoritative_statuses=True,actor_user_id=user.id)
    question(db,project)
    response = client.post(f'/projects/{project.id}/onboarding/complete')
    assert response.status_code == 200, response.text
    completion = response.json()['profile']['completion']
    assert completion['final_approved']
    assert completion['sales_activation_status'] == 'not_ready'
    assert response.json()['profile']['data']['sales_authorization'] is True  # Deferred state never invents a new authorization.
    assert response.json()['profile']['fields']
    assert profile.field_states['sales_authorization']['status'] == 'confirmed'
    assert not completion['capabilities']['meta_lead_ads']['ready']
    assert profile.field_states['campaigns_defined']['status'] == 'deferred'


def test_replaying_editor_navigation_does_not_redirect_out_of_completed_chat(api):
    client,(_,_,_,project,_,_) = api
    body = {'message':'Open review: catalog','client_message_id':str(uuid4())}
    for _ in range(2):
        response = client.post(f'/projects/{project.id}/editor/catalog',json=body)
        assert response.status_code == 200, response.text
        assert response.json().get('redirect_url') is None
