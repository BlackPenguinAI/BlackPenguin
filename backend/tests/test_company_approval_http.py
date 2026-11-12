"""Approval/publication through real Company HTTP and database paths."""
from copy import deepcopy
from unittest.mock import AsyncMock,patch
import pytest
from test_onboarding_ux_2325 import client,context
from app.modules.company_onboarding import services
from app.modules.company_onboarding.router import router
from app.modules.company_onboarding.models import CompanyProfile,OnboardingSession,SenderType
from app.modules.company_onboarding.completion import FIELD_BY_KEY


def ready(api,case,legacy=False,complete=True):
    db,company,user,*_=case;api.app.include_router(router,prefix='/company-onboarding')
    states={d.key:{'status':'confirmed' if d.requirement=='required' else 'not_applicable','applicable':d.requirement=='required'} for d in FIELD_BY_KEY.values() if d.requirement in {'required','conditionally_required'}}
    if not complete:states.pop('official_company_name')
    profile=CompanyProfile(company_id=company.id,profile_data={'official_company_name':'Ready Company','preferred_display_name':'Ready','country':'US','city':'New York','timezone':'America/New_York','headquarters':'New York, US'},field_states=states)
    session=OnboardingSession(company_id=company.id);db.add_all([profile,session]);db.flush()
    ui={'field':None,'input_type':'boolean','label':'Final approval','options':['Approve profile','I need to make changes']}
    if not legacy:ui['answer_actions']={'Approve profile':{'kind':'approve_profile'},'I need to make changes':{'kind':'request_changes'}}
    card=services.save_message(db,session.id,SenderType.AI,'Review',ui_payload=ui)
    return db,profile,session,card


def submit(api,payload):
    with patch('app.modules.company_onboarding.router.generate_llm_response',new=AsyncMock(side_effect=AssertionError('No model'))),patch('app.modules.company_onboarding.router.job_service.enqueue',side_effect=AssertionError('No crawling')):
        return api.post('/company-onboarding/chat',json=payload)


@pytest.mark.parametrize('bound,legacy',[(True,False),(False,False),(True,True),(False,True)])
def test_ready_company_is_published_from_card_or_legacy_text(client,bound,legacy):
    api,case=client;db,profile,session,card=ready(api,case,legacy)
    payload={'message':'Approve profile'}
    if bound:payload['in_reply_to_message_id']=card.id
    response=submit(api,payload);assert response.status_code==200,response.text
    result=response.json();db.refresh(profile);db.refresh(session);db.refresh(card)
    assert result['profile_changed'] and result['field_update_status']=='accepted'
    assert result['profile']['completion']['can_complete'] and profile.final_approved and session.is_completed
    assert profile.published_snapshot and card.response_payload['status']=='accepted'
    assert 'approved successfully' in result['message']['content']


def test_review_navigation_is_not_approval(client):
    api,case=client;db,profile,session,card=ready(api,case)
    response=submit(api,{'message':'I want to review profile'});assert response.status_code==200,response.text
    db.refresh(profile);assert not profile.final_approved and not response.json()['profile_changed']
    assert response.json()['message']['content'].startswith('I understood:')


@pytest.mark.parametrize('mode',['blocked','stale','foreign','repeat'])
def test_no_bypass_of_blockers_or_card_identity(client,mode):
    api,case=client;db,profile,session,card=ready(api,case,complete=mode!='blocked')
    if mode=='stale':
        services.supersede_unanswered_questions(db,session.id)
        services.save_message(db,session.id,SenderType.AI,'New review',ui_payload=card.ui_payload)
    elif mode=='foreign':
        other=OnboardingSession(company_id='foreign-company');db.add(other);db.flush()
        card=services.save_message(db,other.id,SenderType.AI,'Other company',ui_payload=card.ui_payload)
    payload={'message':'Approve profile','in_reply_to_message_id':card.id}
    if mode=='repeat':
        assert submit(api,payload).json()['profile_changed'];db.refresh(profile);published=deepcopy(profile.published_snapshot)
    response=submit(api,payload);assert response.status_code==200,response.text
    db.refresh(profile)
    if mode=='repeat':assert profile.published_snapshot==published
    else:assert not profile.final_approved and not profile.published_snapshot
    assert not response.json()['profile_changed']


def test_marketing_cannot_approve_even_with_complete_profile(client):
    from app.modules.users.models import UserRole
    api,case=client;db,profile,session,card=ready(api,case)
    case[2].role=UserRole.MKT;db.commit()
    response=submit(api,{'message':'Approve profile','in_reply_to_message_id':card.id})
    assert response.status_code==403
    db.refresh(profile);assert not profile.final_approved and not profile.published_snapshot


def test_inconsistent_published_location_still_blocks_approval(client):
    api,case=client;db,profile,session,card=ready(api,case)
    profile.profile_data={**profile.profile_data,'timezone':'Asia/Tokyo'};db.commit()
    response=submit(api,{'message':'Approve profile','in_reply_to_message_id':card.id})
    assert response.status_code==422,response.text
    db.refresh(profile);assert not profile.final_approved and not profile.published_snapshot


def test_document_card_is_not_a_final_approval_card(client):
    api,case=client;db,profile,session,card=ready(api,case)
    card.ui_payload={'field':None,'input_type':'documents','label':'Documents'};db.commit()
    response=submit(api,{'message':'Approve profile','in_reply_to_message_id':card.id})
    assert response.status_code==200,response.text
    db.refresh(profile);assert not profile.final_approved
