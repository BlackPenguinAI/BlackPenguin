from copy import deepcopy
from datetime import datetime,timedelta
import json
import pytest
from app.modules.projects import services
from app.modules.projects.models import MetaAuthorization,MetaConnection,ProjectCampaign,ProjectMessage,SenderType,Project
from app.modules.projects.meta_setup_state import REQUIRED_SCOPES,setup_state
from app.modules.projects.schemas import MetaSetupStateResponse
from app.modules.onboarding_questions import build_next_question,QUESTION_CATALOG,validate_onboarding_value
from app.modules.onboarding_selection import normalize_selection,EXCLUSIVE_OPTIONS
from app.modules.onboarding_question_inventory import question_inventory
from app.modules.users.models import UserRole
from app.modules.company_onboarding import services as company_services
from app.modules.company_onboarding.models import CompanyProfile,OnboardingSession,OnboardingMessage,SenderType as CompanySender
from test_onboarding_ux_2325 import client,context


def auth(case,**kwargs):
    db,company,user,project,profile,item=case
    values={'company_id':company.id,'meta_user_id':'safe-person','meta_user_name':'Account name','token_ciphertext':'PRIVATE-DO-NOT-EXPOSE',
            'scopes':sorted(REQUIRED_SCOPES),'status':'active','expires_at':datetime.utcnow()+timedelta(days=10)}
    values.update(kwargs);value=MetaAuthorization(**values);db.add(value);db.commit();return value


def mapping(case,authorization=None,**kwargs):
    db,company,user,project,profile,item=case
    connection=MetaConnection(company_id=company.id,label='Saved connection',token_ciphertext='PRIVATE-CONNECTION',authorization_id=authorization.id if authorization else None,
        page_id='page-safe',verification_mode='real',verification_status='succeeded',expires_at=datetime.utcnow()+timedelta(days=5))
    db.add(connection);db.flush()
    values={'project_id':project.id,'name':'Saved campaign','platform':'meta','status':'active','lead_form_id':'form-safe','meta_connection_id':connection.id}
    values.update(kwargs);campaign=ProjectCampaign(**values);db.add(campaign);db.commit();return connection,campaign


@pytest.mark.parametrize('role,can_configure',[(UserRole.ADMIN,True),(UserRole.ASSISTANT,True),(UserRole.MKT,False),(UserRole.SALES,False)])
def test_marketing_status_is_readable_and_actions_respect_ui_role(client,role,can_configure):
    api,case=client;db,company,user,project,profile,item=case
    auth(case);user.role=role;db.commit()
    response=api.get(f'/projects/{project.id}/marketing/summary');assert response.status_code==200,response.text
    data=response.json();assert data['meta_setup']['account_status']=='connected' and data['meta_setup']['routing_status']=='not_linked'
    assert data['can_configure_meta'] is can_configure
    assert 'PRIVATE' not in json.dumps(data) and 'token_ciphertext' not in json.dumps(data)
    assert data['meta_setup']==MetaSetupStateResponse(**setup_state(db,project)).model_dump(mode='json')


@pytest.mark.parametrize('mode,status',[('empty','not_connected'),('expired','reconnect_required'),('permissions','permissions_required'),('connected','connected')])
def test_marketing_reports_account_state_independently_of_campaigns(client,mode,status):
    api,case=client;db,company,user,project,profile,item=case
    if mode=='expired':auth(case,expires_at=datetime.utcnow()-timedelta(days=1))
    if mode=='permissions':auth(case,scopes=['pages_show_list'])
    if mode=='connected':auth(case)
    data=api.get(f'/projects/{project.id}/marketing/summary').json()['meta_setup']
    assert data['account_status']==status and data['routing_status']=='not_linked'
    if mode=='expired':assert data['last_authorization']['expires_at']
    if mode=='permissions':assert data['missing_permissions']


@pytest.mark.parametrize('status,ready',[('active',True),('draft',False),('paused',False),('archived',False)])
def test_marketing_lists_inactive_mappings_without_claiming_live_routing(client,status,ready):
    api,case=client;authorization=auth(case);connection,campaign=mapping(case,authorization,status=status)
    data=api.get(f'/projects/{case[3].id}/marketing/summary').json()['meta_setup']
    assert len(data['mappings'])==1 and data['mappings'][0]['ready'] is ready
    assert data['mappings'][0]['campaign_status']==status and data['mappings'][0]['lead_form_id']=='form-safe'
    assert data['routing_status']==('connected' if ready else 'review_required')


@pytest.mark.parametrize('change,reason',[('expired','connection_expired'),('simulated','real_verification_required'),('form','page_or_form_required')])
def test_mapping_failure_has_real_diagnostic_reason(client,change,reason):
    api,case=client;db=case[0];authorization=auth(case);connection,campaign=mapping(case,authorization)
    if change=='expired':connection.expires_at=datetime.utcnow()-timedelta(seconds=1)
    if change=='simulated':connection.verification_mode='simulated'
    if change=='form':campaign.lead_form_id=None
    db.commit();data=api.get(f'/projects/{case[3].id}/marketing/summary').json()['meta_setup']
    assert data['mappings'][0]['ready'] is False and data['mappings'][0]['reason']==reason


def test_marketing_scope_denies_selected_and_foreign_project(client):
    api,case=client;db,company,user,project,profile,item=case
    user.role=UserRole.MKT;user.project_access_scope='selected';db.commit()
    assert api.get(f'/projects/{project.id}/marketing/summary').status_code==404
    assert api.get('/projects/foreign/marketing/summary').status_code==404


def test_other_project_mapping_does_not_leak_into_summary(client):
    api,case=client;db,company,user,project,profile,item=case
    other=Project(company_id=company.id,name='Other project');db.add(other);db.commit()
    authorization=auth(case);mapping(case,authorization,project_id=other.id,name='Other private campaign')
    data=api.get(f'/projects/{project.id}/marketing/summary').json()
    assert data['meta_setup']['mappings']==[] and 'Other private campaign' not in json.dumps(data)


@pytest.mark.parametrize('value,expected',[('Cash; Bank financing',['Cash','Bank financing']),(['Cash','cash','Bank financing'],['Cash','Bank financing']),('Custom option',['Custom option'])])
def test_existing_multi_select_values_are_lists_without_duplicates(value,expected):
    assert normalize_selection('payment_methods',value,QUESTION_CATALOG['payment_methods']['options'])==expected


@pytest.mark.parametrize('value',[['Not applicable','Cash'],'Not applicable; Cash',['Provide later','Cash'],[{'value':'Cash'}],{'cash':True}])
def test_invalid_or_exclusive_mixed_selections_have_readable_errors(value):
    with pytest.raises(ValueError):normalize_selection('payment_methods',value,QUESTION_CATALOG['payment_methods']['options'])


def test_compliance_option_with_semicolon_is_one_exclusive_choice():
    label=EXCLUSIVE_OPTIONS['compliance_notes'][0]
    assert normalize_selection('compliance_notes',label,QUESTION_CATALOG['compliance_notes']['options'])==[label]
    assert validate_onboarding_value('compliance_notes',[label]) is None
    with pytest.raises(ValueError):normalize_selection('compliance_notes',label+'; Financing disclaimer',QUESTION_CATALOG['compliance_notes']['options'])


def test_project_api_normalizes_only_existing_multi_fields_and_keeps_published_version(context):
    db,company,user,project,profile,item=context;published=deepcopy(profile.published_snapshot)
    result=services.apply_field_updates(db,profile,[{'field':'payment_methods','value':'Cash; Bank financing','status':'confirmed'}],allow_authoritative_statuses=True,actor_user_id=user.id)
    assert not result.rejected and profile.profile_data['payment_methods']==['Cash','Bank financing']
    assert profile.published_snapshot==published
    old=deepcopy(profile.profile_data)
    result=services.apply_field_updates(db,profile,[{'field':'compliance_notes','value':['Not applicable','Financing disclaimer'],'status':'confirmed'}],allow_authoritative_statuses=True)
    assert result.rejected[0]['reason']=='invalid_multi_selection' and profile.profile_data==old


def test_project_chat_uses_same_selection_contract(context):
    db,company,user,project,profile,item=context
    question=build_next_question([{'field':'payment_methods','label':'Payment','requirement':'required','status':'missing'}],final_prompt='Review')
    message=services.save_message(db,project.session.id,SenderType.AI,'Choose',ui_payload=question)
    result=services.resolve_answer_to_question(db,session_id=project.session.id,message_id=message.id,answer='Cash; Bank financing',profile=profile)
    assert result.status=='accepted' and result.updates[0]['value']==['Cash','Bank financing']


def test_inventory_does_not_activate_proposed_cardinality_changes():
    before=deepcopy(QUESTION_CATALOG);rows=question_inventory()
    assert len(rows)>80 and {row['scope'] for row in rows}=={'Company','Project'}
    assert all(row['review_status']=='pending_mau_approval' and not row['runtime_changed_by_proposal'] for row in rows)
    proposal=next(row for row in rows if row['field']=='amenities')
    assert proposal['suggested_input_type']=='multi_select' and proposal['current_input_type']=='text'
    assert before==QUESTION_CATALOG and QUESTION_CATALOG['project_type']['input_type']=='single_select'


def test_company_applies_same_list_contract_without_changing_published_values(context):
    db,company,user,project,profile,item=context
    corporate=CompanyProfile(company_id=company.id,profile_data={},field_states={},published_snapshot={'profile_data':{'core_asset_classes':['Office']}})
    db.add(corporate);db.commit();published=deepcopy(corporate.published_snapshot)
    result=company_services.apply_field_updates(db,corporate,[{'field':'core_asset_classes','value':'Office; Retail; office','status':'confirmed'}],allow_authoritative_statuses=True,actor_user_id=user.id)
    assert not result.rejected and corporate.profile_data['core_asset_classes']==['Office','Retail']
    assert corporate.published_snapshot==published
    previous=deepcopy(corporate.profile_data)
    result=company_services.apply_field_updates(db,corporate,[{'field':'core_asset_classes','value':['Retail','Provide later'],'status':'confirmed'}],allow_authoritative_statuses=True)
    assert result.rejected[0]['reason']=='invalid_multi_selection' and corporate.profile_data==previous


@pytest.mark.parametrize('answer,status,value',[
    ('English; Spanish','confirmed',['English','Spanish']),
    ('Not applicable','not_applicable',None),
    ('Provide later','deferred',None),
])
def test_company_persisted_question_distinguishes_lists_from_actions(context,answer,status,value):
    db,company,user,project,profile,item=context
    corporate=CompanyProfile(company_id=company.id,profile_data={},field_states={})
    session=OnboardingSession(company_id=company.id);db.add_all([corporate,session]);db.flush()
    question=build_next_question([{'field':'additional_corporate_languages','label':'Languages','requirement':'conditionally_required','status':'missing'}],final_prompt='Review')
    message=OnboardingMessage(session_id=session.id,sender=CompanySender.AI,content='Choose',ui_payload=question)
    db.add(message);db.commit()
    result=company_services.resolve_answer_to_question(db,session_id=session.id,message_id=message.id,answer=answer,profile=corporate)
    assert result.status=='accepted' and result.updates[0]['status']==status and result.updates[0]['value']==value


def test_prompt_contract_is_derived_from_active_catalog_without_overwriting_config():
    from app.modules.company_onboarding.router import _system_instruction as company_instruction
    from app.modules.projects.router import _system_instruction as project_instruction
    config={'system_prompt':'Saved custom instruction','protocol_prompt':'Saved protocol'};before=deepcopy(config)
    for build in (company_instruction,project_instruction):
        instruction=build(config)
        assert 'Saved custom instruction' in instruction and 'Saved protocol' in instruction
        assert 'MULTI-SELECTION CONTRACT' in instruction and 'payment_methods' in instruction
        assert 'Cardinality proposals pending Mau review are not active' in instruction
    assert config==before


def test_summary_get_does_not_modify_onboarding_or_campaigns(client):
    api,case=client;db,company,user,project,profile,item=case
    authorization=auth(case);connection,campaign=mapping(case,authorization,status='draft')
    before=(deepcopy(profile.profile_data),deepcopy(profile.field_states),profile.draft_revision,db.query(ProjectMessage).count(),campaign.status,connection.updated_at)
    for _ in range(2):assert api.get(f'/projects/{project.id}/marketing/summary').status_code==200
    db.refresh(profile);db.refresh(campaign);db.refresh(connection)
    assert before==(profile.profile_data,profile.field_states,profile.draft_revision,db.query(ProjectMessage).count(),campaign.status,connection.updated_at)


def test_missing_permissions_use_best_single_account_not_combined_scopes(client):
    api,case=client
    scopes=sorted(REQUIRED_SCOPES)
    partial=auth(case,scopes=scopes[:-1],meta_user_name='Nearly complete')
    auth(case,scopes=[scopes[-1]],meta_user_id='other',meta_user_name='Newest but incomplete')
    data=api.get(f'/projects/{case[3].id}/marketing/summary').json()['meta_setup']
    assert data['account_status']=='permissions_required' and data['last_authorization']['id']==partial.id
    assert data['missing_permissions']==[scopes[-1]]


def test_expired_account_blocks_existing_verified_mapping(client):
    api,case=client;authorization=auth(case,expires_at=datetime.utcnow()-timedelta(days=1));mapping(case,authorization)
    state=api.get(f'/projects/{case[3].id}/marketing/summary').json()['meta_setup']
    assert state['account_status']=='reconnect_required' and state['routing_status']=='review_required'
    assert state['mappings'][0]['reason']=='authorization_required' and not state['mappings'][0]['ready']


def test_historical_exclusive_compliance_values_remain_visible_for_review():
    label=EXCLUSIVE_OPTIONS['compliance_notes'][0]
    question=build_next_question([{'field':'compliance_notes','label':'Compliance','requirement':'conditionally_required','status':'pending_confirmation'}],final_prompt='Review',profile_data={'compliance_notes':[label,'Financing disclaimer']})
    assert question['selected_values']==[label,'Financing disclaimer']
    assert validate_onboarding_value('compliance_notes',question['selected_values'])['code']=='invalid_multi_selection'
