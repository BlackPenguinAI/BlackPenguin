"""Regression probes for the independently reproduced price and UX gaps."""
from copy import deepcopy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.postgres import get_db
from app.modules.auth.deps import get_current_user
from app.modules.onboarding_deferrals import router, records, Decision, save, KEY
from app.modules.sales_agent.monetary_policy import validate_monetary_reply
from app.modules.projects import services, catalog_service
from app.modules.projects.router import _next_question, _state_payload
from app.modules.projects.models import ProjectOnboardingSource, ProjectSourceKind, ProjectSourceStatus, ProjectOnboardingProposal, ProjectProposalStatus, ProjectMessage
from app.modules.governance.models import PlatformAuditEvent
from app.modules.users.models import UserRole
from test_onboarding_revisions_and_money import context

CATALOG={'property_types':[{'id':'a','property_type':'Residence A','starting_price':30,'maximum_price':45.75,'currency':'USD'}]}


@pytest.mark.parametrize('text',[
 'Residence A prices range from USD 30–30,000.',
 'Residence A costs 30000 dollars.', 'Residence A cuesta 30000 dólares.',
 'Residence A: 30–30000 USD', 'Residence A: USD 30000–45.75',
 'Residence A: USD 30 to 30000', 'Residence A: 30 hasta 30000 dólares',
 'Residence A: USD 45.75–30', 'Residence A: -30 USD',
 'Residence A: US dollars 30000', 'Residence A: 30000 dólares estadounidenses',
 'Residence A: 30.000 dólares', 'Residence A: 30,000.00 dollars',
 'Residence A: USD 30—30000', 'Residence A: USD 30-30000',
 'Residence A: USD 30–45.75 EUR', 'Residence A: USD 30–45.75 euros',
])
def test_unapproved_range_or_currency_words_are_rejected(text):
    reply,evidence=validate_monetary_reply(text,CATALOG)
    assert evidence['checked'] and evidence['replaced']
    assert reply != text and evidence['original_reply']==text


@pytest.mark.parametrize('text',[
 'Residence A: USD 30–45.75', 'Residence A: 30–45.75 USD',
 'Residence A: 30 dollars', 'Residence A: 30 dólares',
 'Residence A: US dollars 30', 'Residence A: 30 dólares estadounidenses',
 'Residence A: USD 30 to 45.75', 'Residence A: 30 a 45.75 dólares',
 'Residence A: $30', 'Residence A: 45.75 USD', 'How many bedrooms do you prefer?',
 'Residence A: USD 30–45.75 USD', 'Residence A: USD 30–45.75 dollars',
])
def test_approved_prices_and_non_financial_replies_are_preserved(text):
    reply,evidence=validate_monetary_reply(text,CATALOG)
    assert reply==text and not evidence['replaced']


def test_generic_currency_words_do_not_guess_country():
    mixed={'property_types':[{'starting_price':30,'currency':'USD'},{'starting_price':30,'currency':'CAD'}]}
    assert validate_monetary_reply('It costs 30 dollars.',mixed)[1]['replaced']
    assert not validate_monetary_reply('It costs 30 Canadian dollars.',mixed)[1]['replaced']
    pesos={'property_types':[{'starting_price':30,'currency':'MXN'},{'starting_price':30,'currency':'COP'}]}
    assert validate_monetary_reply('Cuesta 30 pesos.',pesos)[1]['replaced']
    assert not validate_monetary_reply('Cuesta 30 pesos mexicanos.',pesos)[1]['replaced']


@pytest.fixture
def api(context):
    db,company,user,project,profile,item=context
    app=FastAPI();app.include_router(router,prefix='/deferrals')
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:user
    with TestClient(app) as client:
        yield client,context


def test_defer_and_resume_preserve_facts_published_version_and_evidence(api):
    client,(db,company,user,project,profile,item)=api
    before=deepcopy(profile.published_snapshot); facts=deepcopy(profile.profile_data)
    revision=profile.draft_revision
    url='/deferrals/project/'+project.id
    payload={'card':'property:'+item.id,'draft':{'name':'Unsaved residence','starting_price':99}}
    response=client.post(url,json=payload)
    assert response.status_code==200 and response.json()['deferrals'][payload['card']]['deferred']
    assert profile.profile_data==facts and profile.published_snapshot==before and profile.final_approved
    assert profile.draft_revision==revision and item.starting_price==30
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Configured for later%')).count()==1
    assert db.query(PlatformAuditEvent).filter_by(event_type='onboarding.card_deferred').count()==1
    assert client.post(url,json=payload).status_code==200
    assert db.query(PlatformAuditEvent).filter_by(event_type='onboarding.card_deferred').count()==1
    resumed=client.post(url,json={'card':payload['card'],'resume':True}).json()['deferrals'][payload['card']]
    assert not resumed['deferred'] and resumed['draft']==payload['draft']
    db.expire_all()
    assert records(profile)[payload['card']]['draft']['name']=='Unsaved residence'
    assert db.query(ProjectMessage).filter(ProjectMessage.content.like('Resumed %')).count()==1


def test_approved_property_save_clears_stale_ui_draft(api):
    client,(db,company,user,project,profile,item)=api
    client.post('/deferrals/project/'+project.id,json={'card':'property:'+item.id,'draft':{'name':'Old unsaved draft'}})
    catalog_service.update(db,project,item,{'name':'Actual saved name'},user_id=user.id)
    assert records(profile)['property:'+item.id]['draft']=={}


def test_source_review_can_wait_without_approving_proposals(api):
    client,(db,company,user,project,profile,item)=api
    services.apply_field_updates(db,profile,[services.user_field_update('project_name','Pending project')],allow_authoritative_statuses=True,actor_user_id=user.id)
    source=ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.UPLOADED_FILE,status=ProjectSourceStatus.READY,name='Brochure')
    db.add(source);db.flush()
    proposal=ProjectOnboardingProposal(source_id=source.id,field_key='project_name',value='Extracted name',status=ProjectProposalStatus.PENDING)
    db.add(proposal);db.commit()
    r=client.post('/deferrals/project/'+project.id,json={'card':'source:'+source.id,'draft':{proposal.id:'Typed but unconfirmed'}})
    assert r.status_code==200
    state=_state_payload(db,project)
    assert state['stage']!='review'
    assert proposal.status==ProjectProposalStatus.PENDING
    assert not state['profile']['completion']['ready_for_confirmation']
    assert 'Typed but unconfirmed' not in str(profile.published_snapshot)


def test_required_questions_are_deferred_not_approved(api):
    client,(db,company,user,project,profile,item)=api
    services.apply_field_updates(db,profile,[services.user_field_update('project_name',None,status='missing')],allow_authoritative_statuses=True)
    response=client.post('/deferrals/project/'+project.id,json={'card':'field:project_name','draft':{'answer':'Unconfirmed answer'}})
    assert response.status_code==200
    assert _next_question(profile)['field']=='project_name'  # Required deferred facts are revisited, never approved.
    assert not services.serialize_profile(profile)['completion']['can_complete']


def test_postponed_meta_does_not_grant_permission(api):
    client,(db,company,user,project,profile,item)=api
    profile.published_snapshot=None;profile.final_approved=False
    states=dict(profile.field_states);states['campaigns_defined']={'status':'missing','applicable':True};states['meta_connection_verified']={'status':'missing','applicable':True};profile.field_states=states;db.commit()
    r=client.post('/deferrals/project/'+project.id,json={'card':'field:campaigns_defined','draft':{'manual':{'page_id':'123456'}}})
    assert r.status_code==200
    assert profile.field_states['campaigns_defined']['status']=='deferred'
    assert not services.serialize_profile(profile)['completion']['capabilities']['meta_lead_ads']['ready']


@pytest.mark.parametrize('role',[UserRole.SALES,UserRole.MKT])
def test_non_managers_cannot_persist_deferrals(api,role):
    client,(db,company,user,project,profile,item)=api
    user.role=role
    assert client.post('/deferrals/project/'+project.id,json={'card':'catalog'}).status_code==403


def test_scope_validation_and_unknown_cards(api):
    client,(db,company,user,project,profile,item)=api
    for card in ('field:unknown','unknown'):
        assert client.post('/deferrals/project/'+project.id,json={'card':card}).status_code==422
    assert client.post('/deferrals/project/'+project.id,json={'card':'source:foreign'}).status_code==404
    assert client.post('/deferrals/company/foreign',json={'card':'team'}).status_code==404


def test_company_team_draft_is_persistent_and_never_creates_a_user(api):
    from app.modules.company_onboarding import services as cs
    from app.modules.company_onboarding.router import _state_payload as company_state
    from app.modules.users.models import User
    client,(db,company,user,project,profile,item)=api
    count=db.query(User).count()
    r=client.post('/deferrals/company/'+company.id,json={'card':'team','draft':{'email':'not-invited@example.test','role':'sales'}})
    assert r.status_code==200
    cp=cs.get_or_create_profile(db,company.id)
    assert records(cp)['team']['draft']['email']=='not-invited@example.test'
    assert not cp.final_approved and db.query(User).count()==count


def test_resuming_meta_reopens_configuration_without_granting_permission(api):
    client,(db,company,user,project,profile,item)=api
    profile.published_snapshot=None;profile.final_approved=False
    states=dict(profile.field_states)
    for key in ('campaigns_defined','meta_connection_verified'): states[key]={'status':'missing','applicable':True}
    profile.field_states=states;db.commit()
    url='/deferrals/project/'+project.id
    client.post(url,json={'card':'field:campaigns_defined','draft':{'manual':{'campaign_name':'Unsaved'}}})
    assert client.post(url,json={'card':'field:campaigns_defined','resume':True}).status_code==200
    assert profile.field_states['campaigns_defined']['status']=='missing'
    assert _next_question(profile)['field']=='campaigns_defined'
    assert not services.serialize_profile(profile)['completion']['capabilities']['meta_lead_ads']['ready']


def test_final_approval_can_wait_without_publishing(api):
    client,(db,company,user,project,profile,item)=api
    services.apply_field_updates(db,profile,[services.user_field_update('project_name','Unpublished revision')],allow_authoritative_statuses=True,actor_user_id=user.id)
    old=profile.published_snapshot['revision']
    url='/deferrals/project/'+project.id
    assert client.post(url,json={'card':'final_approval'}).status_code==200
    assert _next_question(profile)['label']=='Saved for later'
    assert not profile.final_approved and profile.published_snapshot['revision']==old
    client.post(url,json={'card':'final_approval','resume':True})
    assert _next_question(profile)['label']=='Final approval'
    services.complete_onboarding(db,project,user.id)
    assert not records(profile)['final_approval']['deferred']


@pytest.mark.parametrize('bad', [{'manual':{'access_token':'do-not-store'}},{'api_key':'do-not-store'}])
def test_credentials_cannot_be_stored_in_ui_drafts(api,bad):
    client,(db,company,user,project,profile,item)=api
    assert client.post('/deferrals/project/'+project.id,json={'card':'catalog','draft':bad}).status_code==422
    assert 'do-not-store' not in str(profile.field_sources)


def test_saving_a_material_form_does_not_restore_its_old_ui_draft(api):
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.modules.projects.router import create_sales_asset
    client,(db,company,user,project,profile,item)=api
    client.post('/deferrals/project/'+project.id,json={'card':'materials','draft':{'display_name':'Old form'}})
    payload=SimpleNamespace(model_dump=lambda:{})
    def persisted(*args,**kwargs):
        assert records(profile)['materials']['draft']=={}
        db.commit()
        return object()
    with patch('app.modules.projects.router.sales_asset_service.create',side_effect=persisted),patch('app.modules.projects.router.sales_asset_service.serialize',return_value={}):
        create_sales_asset(project_id=project.id,payload=payload,db=db,current_user=user)
    db.expire_all()
    assert records(profile)['materials']['draft']=={}


def test_company_resume_team_then_continue_closes_the_resumed_card(api):
    from app.modules.company_onboarding.router import continue_company_onboarding_after_team
    from app.modules.company_onboarding import services as cs
    client,(db,company,user,project,profile,item)=api
    url='/deferrals/company/'+company.id
    client.post(url,json={'card':'team','draft':{'email':'unsent@example.test'}})
    client.post(url,json={'card':'team','resume':True})
    continue_company_onboarding_after_team(db=db,current_user=user)
    cp=cs.get_or_create_profile(db,company.id);db.expire_all()
    assert not records(cp)['team']['resumed'] and records(cp)['team']['draft']=={}


@pytest.mark.parametrize('text',['Residence A prices range from USD 30–30,000.','Residence A costs 30000 dollars.','Residence A cuesta 30000 dólares.'])
def test_previously_failing_claims_are_blocked_at_actual_dispatch(context,text):
    import asyncio
    from unittest.mock import AsyncMock,patch
    from app.modules.sales_agent.live_service import _dispatch
    from app.modules.sales_agent.models import SalesConversation,AgentRun,OutboundMessage
    from app.modules.sales_crm.models import Lead
    db,company,user,project,profile,item=context
    lead=Lead(company_id=company.id,project_id=project.id,full_name='Price regression',phone='+12025550111',consent_status='granted')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=company.id,project_id=project.id,lead_id=lead.id,provider='telnyx',channel='sms',is_paused=False)
    db.add(conversation);db.flush()
    run=AgentRun(conversation_id=conversation.id,event_id='price-regression',mode='live',status='completed',graph_version='test',toolset_version='test',prompt_snapshot={},model='test',input_snapshot={},output_snapshot={'reply':text})
    db.add(run);db.commit()
    provider=AsyncMock(return_value={'sid':'mock','status':'sent'})
    with patch('app.modules.sales_agent.live_service.send_sms',provider),patch('app.modules.sales_agent.live_service.send_message',provider):
        message=asyncio.run(_dispatch(db,conversation=conversation,lead=lead,content=text,role='assistant',agent_run_id=run.id))
    assert message.content!=text and '30,000' not in message.content and '30000' not in message.content
    assert provider.call_args.kwargs['body']==message.content==run.output_snapshot['reply']==db.query(OutboundMessage).one().content
