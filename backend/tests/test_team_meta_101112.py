"""Issues 10-12: real HTTP/DB contracts; Meta mocked, no live messages."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.core.secret_store import encrypt_secret
from app.modules.governance.models import PlatformAuditEvent
from app.modules.onboarding_deferrals import router as deferrals_router
from app.modules.project_team.router import router as team_router, upsert_assignment
from app.modules.project_team.schemas import AssignmentUpsert
from app.modules.project_team.models import ProjectUserAssignment
from app.modules.projects import meta_oauth_service as oauth
from app.modules.projects.models import MetaAuthorization, MetaConnection, Project, ProjectCampaign, ProjectMessage
from app.modules.projects.meta_setup_state import REQUIRED_SCOPES, setup_state
from app.modules.system_settings.models import MetaOAuthAttempt
from app.modules.users.models import User, UserRole
from app.modules.users.project_access import sync_user_project_access, sync_all_scope_users_for_project

def authorization(db, company, **kwargs):
    item = MetaAuthorization(company_id=company.id, meta_user_id='meta-person', meta_user_name='Meta Person',
        token_ciphertext=encrypt_secret('mock-user-token'), scopes=sorted(REQUIRED_SCOPES), status='active')
    for key, value in kwargs.items(): setattr(item, key, value)
    db.add(item); db.commit()
    return item

class MetaClient:
    def __init__(self, responses): self.responses, self.calls = responses, []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    def get(self, url, **kwargs):
        self.calls.append(('GET', url))
        status, body = self.responses[url.split('/v26.0')[-1]]
        return httpx.Response(status, json=body, request=httpx.Request('GET', url))
    def post(self, url, **kwargs):
        self.calls.append(('POST', url))
        return httpx.Response(200, json={'success':True}, request=httpx.Request('POST', url))

@pytest.fixture
def meta(monkeypatch):
    config = SimpleNamespace(app_id='app', redirect_uri='https://blackpenguin.ai/api/v1/projects/integrations/meta/oauth/callback',
        graph_api_version='v26.0', login_config_id='login-config', requested_scopes=[])
    monkeypatch.setattr(oauth.system_settings, 'meta_platform_credentials', lambda db:(config, 'mock-app-secret'))
    responses = {
        '/oauth/access_token':(200,{'access_token':'mock-long-lived-token','expires_in':3600}),
        '/me':(200,{'id':'meta-person','name':'Meta Person'}),
        '/me/permissions':(200,{'data':[{'permission':s,'status':'granted'} for s in REQUIRED_SCOPES]}),
        '/me/accounts':(200,{'data':[{'id':'page-1','name':'Page','access_token':'mock-page-token'}]}),
        '/me/adaccounts':(200,{'data':[{'id':'act_123','account_id':'123','name':'Ads'}]}),
        '/page-1/leadgen_forms':(200,{'data':[{'id':'form-1','name':'Form','status':'ACTIVE'}]}),
        '/campaign-1':(200,{'id':'campaign-1','account_id':'123'}),
        '/adset-1':(200,{'id':'adset-1','account_id':'123','campaign_id':'campaign-1'}),
        '/ad-1':(200,{'id':'ad-1','account_id':'123','campaign_id':'campaign-1','adset_id':'adset-1',
            'creative':{'object_story_spec':{'link_data':{'call_to_action':{'value':{'lead_gen_form_id':'form-1'}}}}}}),
    }
    client = MetaClient(responses)
    class AsyncClient(MetaClient):
        async def get(self, url, **kwargs): return client.get(url, **kwargs)
    monkeypatch.setattr(oauth.httpx, 'Client', lambda **kwargs:client)
    monkeypatch.setattr(oauth.httpx, 'AsyncClient', lambda **kwargs:AsyncClient(responses))
    return client

def configure(context, auth, **kwargs):
    db, company, user, project, profile, item = context
    return oauth.configure_project_setup(db, project=project, authorization_id=auth.id,
        page_id='page-1', ad_account_id='123', lead_form_id='form-1', campaign_name='Explicit mapping', **kwargs)

@pytest.mark.parametrize('responsibility', ['sales','marketing'])
def test_admin_assignment_has_both_capabilities_without_creating_a_user(context, responsibility):
    db, company, user, project, profile, item = context
    count = db.query(User).count()
    response = upsert_assignment(project.id, user.id, AssignmentUpsert(user_id=user.id, responsibility=responsibility), db, user)
    assert response['sales_enabled'] and response['marketing_enabled']
    assert db.query(User).count() == count

@pytest.mark.parametrize('marketing', [True, False])
def test_reassigning_admin_preserves_existing_marketing_exception(context, marketing):
    db, company, user, project, profile, item = context
    db.add(ProjectUserAssignment(project_id=project.id, user_id=user.id, responsibility='sales', sales_enabled=True, marketing_enabled=marketing)); db.commit()
    response = upsert_assignment(project.id, user.id, AssignmentUpsert(user_id=user.id, responsibility='sales'), db, user)
    assert response['marketing_enabled'] is marketing

def test_assignment_rejects_foreign_or_incompatible_user(api):
    client, (db, company, user, project, profile, item) = api
    client.app.include_router(team_router, prefix='/projects')
    sales = User(company_id=company.id, email='sales@101112.test', hashed_password='unused', role=UserRole.SALES)
    db.add(sales); db.commit()
    for target, body in [(sales.id, {'marketing_enabled':True}), ('foreign-user', {})]:
        response = client.put(f'/projects/{project.id}/team/{target}', json={'user_id':target,'responsibility':'sales',**body})
        assert response.status_code == 422
    assert db.query(ProjectUserAssignment).count() == 0

def test_all_scope_includes_future_project_selected_scope_remains_unchanged(context):
    db, company, user, project, profile, item = context
    selected = User(company_id=company.id, email='selected@101112.test', hashed_password='unused', role=UserRole.SALES)
    db.add(selected); db.flush()
    sync_user_project_access(db,user=user,scope='all',project_ids=[])
    sync_user_project_access(db,user=selected,scope='selected',project_ids=[project.id])
    future = Project(company_id=company.id,name='Future Project'); db.add(future); db.flush()
    sync_all_scope_users_for_project(db,future); db.commit()
    current = db.query(ProjectUserAssignment).filter_by(project_id=future.id).one()
    assert current.user_id == user.id and current.sales_enabled and current.marketing_enabled
    assert selected.project_access_scope == 'selected'

def test_account_authorization_does_not_create_project_route_or_approve_fields(context, meta):
    db, company, user, project, profile, item = context
    published = deepcopy(profile.published_snapshot)
    state = oauth.start_oauth(db,project=project,user=user)['state']
    auth, target = asyncio.run(oauth.complete_oauth(db,state=state,code='mock-code'))
    assert target == project.id and auth.company_id == company.id
    assert db.query(ProjectCampaign).count() == 0 and db.query(MetaConnection).count() == 0
    assert profile.published_snapshot == published
    assert setup_state(db,project)['account_status'] == 'connected'
    assert setup_state(db,project)['routing_status'] == 'not_linked'
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Meta account authorization saved%')).count() == 1
    event = db.query(PlatformAuditEvent).filter_by(event_type='meta.account_authorized').one()
    assert 'token' not in str(event.payload_json) and state not in str(event.payload_json)
    with pytest.raises(HTTPException): asyncio.run(oauth.complete_oauth(db,state=state,code='mock-code'))

def test_step_two_can_be_deferred_and_resumed_without_losing_account_or_selections(api):
    client, (db, company, user, project, profile, item) = api
    client.app.include_router(deferrals_router, prefix='/deferrals')
    auth = authorization(db,company)
    draft = {'oauth':{'authorization_id':auth.id,'page_id':'page-1','lead_form_id':'form-1'}}
    url = f'/deferrals/project/{project.id}'
    assert client.post(url,json={'card':'field:campaigns_defined','draft':draft}).status_code == 200
    response = client.post(url,json={'card':'field:campaigns_defined','resume':True})
    assert response.json()['deferrals']['field:campaigns_defined']['draft'] == draft
    db.expire_all()
    assert db.get(MetaAuthorization,auth.id).status == 'active'
    assert db.query(ProjectCampaign).count() == 0

@pytest.mark.parametrize('status,scopes,expired,expected', [
    ('active',REQUIRED_SCOPES,False,'connected'),('active',{'ads_read'},False,'permissions_required'),
    ('revoked',REQUIRED_SCOPES,False,'reconnect_required'),('active',REQUIRED_SCOPES,True,'reconnect_required'),
])
def test_account_status_reports_permissions_and_expiration(context,status,scopes,expired,expected):
    db, company, user, project, profile, item = context
    authorization(db,company,status=status,scopes=list(scopes),expires_at=datetime.utcnow()-timedelta(seconds=1) if expired else None)
    result = setup_state(db,project)
    assert result['account_status'] == expected and result['routing_status'] == 'not_linked'
    assert 'token' not in str(result)

def test_state_and_asset_routes_are_company_scoped_and_deny_sales(api, meta):
    client, (db, company, user, project, profile, item) = api
    from app.modules.companies.models import Company
    foreign = Company(name='Foreign'); db.add(foreign); db.flush()
    foreign_project = Project(company_id=foreign.id,name='Foreign Project'); db.add(foreign_project); db.commit()
    auth = authorization(db,foreign)
    assert client.get(f'/projects/{foreign_project.id}/meta/setup-state').status_code == 404
    assert client.get(f'/projects/{project.id}/meta/oauth/assets',params={'authorization_id':auth.id}).status_code == 404
    user.role=UserRole.SALES; db.commit()
    assert client.get(f'/projects/{project.id}/meta/setup-state').status_code == 403
    assert not meta.calls

def test_verified_project_mapping_is_explicit_idempotent_and_not_other_projects(context, meta):
    db, company, user, project, profile, item = context
    auth = authorization(db,company)
    before = deepcopy(profile.published_snapshot)
    a,b = configure(context,auth,external_campaign_id='campaign-1',external_adset_id='adset-1',external_ad_id='ad-1')
    c,d = configure(context,auth,external_campaign_id='campaign-1',external_adset_id='adset-1',external_ad_id='ad-1')
    assert (a.id,b.id) == (c.id,d.id)
    assert db.query(ProjectCampaign).count() == 1
    assert setup_state(db,project)['routing_status'] == 'connected'
    another = Project(company_id=company.id,name='No mapping'); db.add(another); db.commit()
    assert setup_state(db,another)['routing_status'] == 'not_linked'
    assert profile.published_snapshot == before
    auth.status='revoked'; db.commit()
    assert setup_state(db,project)['routing_status'] == 'review_required'

@pytest.mark.parametrize('mismatch', ['account','campaign','adset','form','instagram','inactive_form'])
def test_mapping_rejects_forged_asset_hierarchy_before_subscription(context, meta, mismatch):
    db, company, user, project, profile, item = context
    auth = authorization(db,company)
    kwargs = dict(external_campaign_id='campaign-1',external_adset_id='adset-1',external_ad_id='ad-1')
    if mismatch == 'account': meta.responses['/campaign-1'][1]['account_id'] = 'foreign'
    if mismatch == 'campaign': meta.responses['/adset-1'][1]['campaign_id'] = 'other'
    if mismatch == 'adset': meta.responses['/ad-1'][1]['adset_id'] = 'other'
    if mismatch == 'form': meta.responses['/ad-1'][1]['creative']['object_story_spec']['link_data']['call_to_action']['value']['lead_gen_form_id'] = 'other'
    if mismatch == 'instagram': kwargs['instagram_account_id'] = 'foreign'
    if mismatch == 'inactive_form': meta.responses['/page-1/leadgen_forms'][1]['data'][0]['status'] = 'ARCHIVED'
    with pytest.raises(HTTPException) as exc: configure(context,auth,**kwargs)
    assert exc.value.status_code == 422
    assert not any(method == 'POST' for method,url in meta.calls)
    assert db.query(ProjectCampaign).count() == 0

def test_shared_form_route_cannot_accidentally_be_assigned_to_another_project(context, meta):
    db, company, user, project, profile, item = context
    auth = authorization(db,company); configure(context,auth)
    another = Project(company_id=company.id,name='Another'); db.add(another); db.commit()
    with pytest.raises(HTTPException) as exc:
        oauth.configure_project_setup(db,project=another,authorization_id=auth.id,page_id='page-1',ad_account_id='123',lead_form_id='form-1',campaign_name='Forbidden')
    assert exc.value.status_code == 409
    assert db.query(ProjectCampaign).count() == 1

@pytest.mark.parametrize('failure', ['expired','used','unknown','inactive_user','changed_company'])
def test_invalid_oauth_attempt_does_not_exchange_tokens(context,meta,failure):
    db, company, user, project, profile, item = context
    state = oauth.start_oauth(db,project=project,user=user)['state']
    attempt = db.query(MetaOAuthAttempt).one()
    if failure == 'expired': attempt.expires_at=datetime.utcnow()-timedelta(seconds=1)
    if failure == 'used': attempt.consumed_at=datetime.utcnow()
    if failure == 'unknown': state='forged-state'
    if failure == 'inactive_user': user.is_active=False
    if failure == 'changed_company': user.company_id=None
    db.commit()
    with pytest.raises(HTTPException): asyncio.run(oauth.complete_oauth(db,state=state,code='mock-code'))
    assert not meta.calls and db.query(MetaAuthorization).count() == 0

def test_callback_cancellation_consumes_state_and_returns_safe_bridge(api, meta):
    client, (db, company, user, project, profile, item) = api
    state = oauth.start_oauth(db,project=project,user=user)['state']
    response = client.get('/projects/integrations/meta/oauth/callback',params={'state':state,'error':'</script><img src=x onerror=alert(1)>'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert 'postMessage' in response.text and 'frame-ancestors' in response.headers['content-security-policy']
    assert '</script><img' not in response.text and 'authorization was cancelled' in response.text
    assert f'/app/projects/{project.id}/onboarding?' in response.text
    assert db.query(MetaOAuthAttempt).one().consumed_at
    assert not meta.calls

def test_success_callback_returns_nonce_and_project_but_no_token(api, meta):
    client, (db, company, user, project, profile, item) = api
    start=client.get(f'/projects/{project.id}/meta/oauth/start')
    assert start.status_code == 200, start.text
    state=start.json()['state']
    response=client.get('/projects/integrations/meta/oauth/callback',params={'state':state,'code':'mock-code'})
    assert response.status_code == 200
    assert project.id in response.text and state in response.text
    assert 'mock-code' not in response.text and 'mock-long-lived-token' not in response.text
    assert 'Return to Project onboarding' in response.text


@pytest.mark.parametrize('role', [UserRole.ADMIN, UserRole.SALES])
def test_project_assignment_does_not_override_selected_project_exceptions(api, role):
    client, (db, company, user, project, profile, item) = api
    user.email = 'admin-101112@example.com'
    client.app.include_router(team_router, prefix='/projects')
    limited = User(company_id=company.id, email='limited@101112.test', hashed_password='unused', role=role, project_access_scope='selected')
    db.add(limited); db.commit()
    candidates = client.get(f'/projects/{project.id}/team/candidates').json()
    assert limited.id not in [row['id'] for row in candidates]
    response = client.put(f'/projects/{project.id}/team/{limited.id}', json={'user_id':limited.id,'responsibility':'sales','sales_enabled':True})
    assert response.status_code == 422 and 'Team / Users' in response.json()['detail']
    assert limited.project_access_scope == 'selected'


def test_explicit_sales_assignment_preserves_marketing_and_calendar_exceptions(context):
    db, company, user, project, profile, item = context
    db.add(ProjectUserAssignment(project_id=project.id,user_id=user.id,responsibility='marketing',sales_enabled=False,marketing_enabled=True,accepts_appointments=False)); db.commit()
    response=upsert_assignment(project.id,user.id,AssignmentUpsert(user_id=user.id,responsibility='sales',sales_enabled=True),db,user)
    assert response['sales_enabled'] and response['marketing_enabled'] and not response['accepts_appointments']


def test_two_step_mapping_via_onboarding_action_keeps_history_and_is_idempotent(api, meta):
    from uuid import uuid4
    from app.modules.projects import services
    from app.modules.projects.models import SenderType
    client, (db, company, user, project, profile, item) = api
    auth=authorization(db,company)
    published=deepcopy(profile.published_snapshot)
    question=services.save_message(db,project.session.id,SenderType.AI,'Select Project assets',ui_payload={'input_type':'meta_lead_setup','field':'campaigns_defined','label':'Meta','prompt':'Select Project assets'})
    payload={'action':'complete_meta_oauth_setup','question_message_id':question.id,'client_action_id':str(uuid4()),'meta_authorization_id':auth.id,'page_id':'page-1','ad_account_id':'act_123','lead_form_id':'form-1','campaign_name':'Explicit HTTP route'}
    response=client.post(f'/projects/{project.id}/onboarding/actions',json=payload)
    assert response.status_code == 200, response.text
    assert client.post(f'/projects/{project.id}/onboarding/actions',json=payload).status_code == 200
    assert db.query(ProjectCampaign).count() == 1 and db.query(MetaConnection).count() == 1
    db.refresh(question);db.refresh(profile)
    assert question.content == 'Select Project assets' and question.response_payload['status'] == 'accepted'
    assert profile.published_snapshot == published and not profile.final_approved
    state=client.get(f'/projects/{project.id}/meta/setup-state')
    assert state.status_code == 200 and state.json()['routing_status'] == 'connected'
    assert 'token' not in state.text

