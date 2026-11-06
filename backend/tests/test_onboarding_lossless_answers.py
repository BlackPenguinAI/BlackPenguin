"""Lossless selections through real chat HTTP/DB paths; no external calls."""
from copy import deepcopy
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from test_onboarding_ux_2325 import client, context
from app.modules.company_onboarding import services as company_services
from app.modules.company_onboarding.models import CompanyProfile, OnboardingSession, OnboardingMessage, SenderType as CompanySender
from app.modules.company_onboarding.router import router as company_router
from app.modules.company_onboarding.schemas import ChatMessagePayload as CompanyPayload
from app.modules.projects import services
from app.modules.projects.models import ProjectMessage, SenderType, ProjectOnboardingSource
from app.modules.projects.schemas import ChatMessagePayload as ProjectPayload
from app.modules.onboarding_questions import build_next_question


def project_question(case, field='payment_methods', values=None):
    db,company,user,project,profile,item=case
    question=build_next_question([{'field':field,'label':field,'requirement':'required','status':'pending_confirmation'}],final_prompt='Review',profile_data={field:values or []})
    return services.save_message(db,project.session.id,SenderType.AI,'Review choices',ui_payload=question)


def company_question(api,case,field='core_asset_classes',values=None):
    db,company,user,project,profile,item=case
    api.app.include_router(company_router,prefix='/company-onboarding')
    corporate=CompanyProfile(company_id=company.id,profile_data={field:values or []},field_states={})
    session=OnboardingSession(company_id=company.id);db.add_all([corporate,session]);db.flush()
    question=build_next_question([{'field':field,'label':field,'requirement':'conditionally_required','status':'pending_confirmation'}],final_prompt='Review',profile_data=corporate.profile_data)
    message=company_services.save_message(db,session.id,CompanySender.AI,'Review choices',ui_payload=question)
    return corporate,session,message


@pytest.mark.parametrize('values',[
    ['Bank financing, subject to approval'],
    ['Cash; staged payments by agreement','Bank financing'],
    ['Custom payment: flexible, reviewed; monthly','Cash'],
    ['Update Meta permissions','Cash'],
])
def test_project_http_selection_preserves_boundaries_audit_and_published_profile(client,values):
    api,case=client;db,company,user,project,profile,item=case
    published=deepcopy(profile.published_snapshot);question=project_question(case,values=values)
    message_id=str(uuid4());payload={'message':'untrusted display text','in_reply_to_message_id':question.id,'selected_values':values,'client_message_id':message_id}
    with patch('app.modules.projects.router.generate_llm_response',new=AsyncMock(side_effect=AssertionError('No model call'))):
        response=api.post(f'/projects/{project.id}/chat',json=payload)
    assert response.status_code==200,response.text
    db.refresh(profile);db.refresh(question)
    assert profile.profile_data['payment_methods']==values and profile.published_snapshot==published
    assert question.response_payload['selected_values']==values
    assert db.get(ProjectMessage,message_id).content=='; '.join(values)
    assert db.query(ProjectOnboardingSource).count()==0
    count=db.query(ProjectMessage).count()
    assert api.post(f'/projects/{project.id}/chat',json=payload).status_code==200
    assert db.query(ProjectMessage).count()==count
    reopened=project_question(case,values=profile.profile_data['payment_methods'])
    assert reopened.ui_payload['selected_values']==values


@pytest.mark.parametrize('structured',[True,False])
def test_company_four_social_links_are_not_truncated_or_recrawled(client,structured):
    api,case=client;db=case[0]
    urls=['https://www.linkedin.com/company/example','https://www.instagram.com/example','https://www.facebook.com/example','https://www.youtube.com/@example']
    corporate,session,question=company_question(api,case,'corporate_social_profiles',urls)
    payload={'message':'; '.join(urls),'in_reply_to_message_id':question.id}
    if structured:payload['selected_values']=urls
    with patch('app.modules.company_onboarding.router.generate_llm_response',new=AsyncMock(side_effect=AssertionError('No model call'))),patch('app.modules.company_onboarding.router.job_service.enqueue',side_effect=AssertionError('No crawling')):
        response=api.post('/company-onboarding/chat',json=payload)
    assert response.status_code==200,response.text
    db.refresh(corporate);db.refresh(question)
    assert corporate.profile_data['corporate_social_profiles']==urls
    assert response.json()['source_actions']==[]
    if structured:assert question.response_payload['selected_values']==urls


def test_company_http_custom_punctuation_survives_save_and_reopen(client):
    api,case=client;db=case[0];values=['Residential, mixed-use projects','Office; storage']
    corporate,session,question=company_question(api,case,values=values)
    response=api.post('/company-onboarding/chat',json={'message':'selection','in_reply_to_message_id':question.id,'selected_values':values})
    assert response.status_code==200,response.text
    db.refresh(corporate);db.refresh(question)
    assert corporate.profile_data['core_asset_classes']==values
    assert question.response_payload['selected_values']==values
    assert build_next_question([{'field':'core_asset_classes','label':'Assets','requirement':'required','status':'pending_confirmation'}],final_prompt='Review',profile_data=corporate.profile_data)['selected_values']==values


@pytest.mark.parametrize('schema',[CompanyPayload,ProjectPayload])
@pytest.mark.parametrize('values',[[],[None],[True],[''],[' '*4],['Cash','']])
def test_selection_payload_rejects_empty_and_nontext_values(schema,values):
    with pytest.raises(ValidationError):schema(message='Answer',in_reply_to_message_id='q',selected_values=values)


@pytest.mark.parametrize('schema',[CompanyPayload,ProjectPayload])
def test_selection_requires_explicit_question_and_has_bounded_size(schema):
    with pytest.raises(ValidationError):schema(message='Answer',selected_values=['Cash'])
    with pytest.raises(ValidationError):schema(message='Answer',in_reply_to_message_id='q',selected_values=['a'*20001])
    assert schema(message='Old client text').selected_values is None


@pytest.mark.parametrize('scope',['project','company'])
@pytest.mark.parametrize('kind',['single','stale','foreign','exclusive'])
def test_bound_selections_cannot_change_wrong_questions_or_apply_control_actions(client,scope,kind):
    api,case=client;db,company,user,project,profile,item=case
    if scope=='project':
        target=profile;question=project_question(case,'project_type' if kind=='single' else 'payment_methods')
        endpoint=f'/projects/{project.id}/chat'
    else:
        target,session,question=company_question(api,case,'primary_business_model' if kind=='single' else 'core_asset_classes')
        endpoint='/company-onboarding/chat'
    if kind=='stale':question.response_payload={'status':'accepted','answer':'Earlier answer'};db.commit()
    before=deepcopy(target.profile_data);snapshot=deepcopy(question.response_payload)
    values=['Cash','Not applicable'] if kind=='exclusive' else ['Cash']
    response=api.post(endpoint,json={'message':'Approve profile','in_reply_to_message_id':'foreign-question' if kind=='foreign' else question.id,'selected_values':values})
    assert response.status_code==(422 if kind=='foreign' else 200),response.text
    db.refresh(target);db.refresh(question)
    assert target.profile_data==before
    if kind!='foreign':assert response.json()['field_update_status']=='rejected'
    if kind=='stale':assert question.response_payload==snapshot


def test_source_discovery_keeps_its_limit_but_explicit_social_parsing_does_not():
    text=' '.join(f'https://example.com/profile{i}' for i in range(7))
    assert len(company_services.extract_urls(text))==3
    assert len(company_services.extract_urls(text,limit=None))==7


def test_old_question_text_transport_protects_saved_custom_labels(context):
    values=['Bank financing, subject to approval','Cash; staged payments by agreement']
    question=project_question(context,values=values)
    result=services.resolve_answer_to_question(context[0],session_id=context[3].session.id,message_id=question.id,answer='; '.join(values),profile=context[4])
    assert result.status=='accepted' and result.updates[0]['value']==values


@pytest.mark.parametrize('scope',['project','company'])
def test_valid_question_from_another_session_cannot_receive_a_selection(client,scope):
    api,case=client;db,company,user,project,profile,item=case
    if scope=='project':
        current=project_question(case)
        from app.modules.projects.models import ProjectSession
        from app.modules.projects.models import Project
        other_project=Project(company_id=company.id,name='Other onboarding');db.add(other_project);db.flush()
        other=ProjectSession(project_id=other_project.id)
        db.add(other);db.flush();foreign=services.save_message(db,other.id,SenderType.AI,'Other question',ui_payload=current.ui_payload)
        endpoint=f'/projects/{project.id}/chat'
    else:
        corporate,session,current=company_question(api,case)
        from app.modules.companies.models import Company
        other_company=Company(name='Foreign tenant',country_code='US');db.add(other_company);db.flush()
        other=OnboardingSession(company_id=other_company.id);db.add(other);db.flush()
        foreign=company_services.save_message(db,other.id,CompanySender.AI,'Other question',ui_payload=current.ui_payload)
        endpoint='/company-onboarding/chat'
    snapshot=deepcopy(current.response_payload)
    result=api.post(endpoint,json={'message':'Cash','in_reply_to_message_id':foreign.id,'selected_values':['Cash']})
    assert result.status_code==422,result.text
    db.refresh(current);db.refresh(foreign)
    assert current.response_payload==snapshot and foreign.response_payload is None
