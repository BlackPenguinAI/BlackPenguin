from copy import deepcopy
from bs4 import BeautifulSoup
import pytest
from test_price_ranges_and_deferrals import api
from test_onboarding_revisions_and_money import context
from app.modules.onboarding_deferrals import records
from app.modules.onboarding_questions import build_next_question
from app.modules.onboarding_answers import question_selection
from app.modules.projects import services
from app.modules.projects.models import SenderType
from app.modules.company_onboarding import services as companies
from app.modules.company_onboarding.models import SenderType as CompanySender
from app.modules.company_onboarding.source_service import _structured_company_facts


@pytest.mark.parametrize('scope',['company','project'])
def test_question_bound_deferral_persists_exact_selections_without_approval(api,scope):
    client,(db,company,user,project,profile,item)=api
    field='payment_methods' if scope=='project' else 'corporate_compliance_information'
    ui=build_next_question([{'field':field,'label':'Test','requirement':'conditionally_required'}],final_prompt='Review')
    if scope=='project':
        owner=profile;entity=project.id
        msg=services.save_message(db,project.session.id,SenderType.AI,'Choose',ui_payload=ui)
    else:
        owner=companies.get_or_create_profile(db,company.id);entity=company.id
        session=companies.get_or_create_session(db,company.id)
        msg=companies.save_message(db,session.id,CompanySender.AI,'Choose',ui_payload=ui)
    facts=deepcopy(owner.profile_data);published=deepcopy(owner.published_snapshot)
    selected=[ui['options'][0],ui['options'][1]]
    url=f'/deferrals/{scope}/{entity}'
    payload={'card':'field:'+field,'question_message_id':msg.id,'draft':{'selected_values':selected}}
    response=client.post(url,json=payload)
    assert response.status_code==200,response.text
    assert owner.profile_data==facts and owner.published_snapshot==published
    assert records(owner)['field:'+field]['draft']['selected_values']==selected
    assert client.post(url,json={'card':'field:'+field,'resume':True}).status_code==200
    db.expire_all()
    question=build_next_question([{'field':field,'label':'Test','requirement':'conditionally_required'}],final_prompt='Review',profile_data=owner.profile_data,profile_sources=owner.field_sources)
    assert question['selected_values']==selected
    if scope=='project':
        from app.modules.projects.router import router as project_router
        client.app.include_router(project_router,prefix='/projects')
        response=client.get(f'/projects/{project.id}/chat/state')
        assert response.status_code==200,response.text
        assert response.json()['next_question']['selected_values']==selected, response.json()['next_question']
        assert response.json()['messages'][-1]['ui_payload']['selected_values']==selected
    assert 'deferred' not in str(owner.profile_data)


@pytest.mark.parametrize('change',['foreign','wrong_field','answered','invalid_values'])
def test_draft_binding_rejects_stale_foreign_or_invalid_questions(api,change):
    client,(db,company,user,project,profile,item)=api
    ui=build_next_question([{'field':'payment_methods','label':'Payments'}],final_prompt='Review')
    msg=services.save_message(db,project.session.id,SenderType.AI,'Choose',ui_payload=ui)
    payload={'card':'field:payment_methods','question_message_id':msg.id,'draft':{'selected_values':['Cash']}}
    if change=='foreign':payload['question_message_id']='unrelated-question'
    elif change=='wrong_field':payload['card']='field:project_name'
    elif change=='answered':msg.response_payload={'status':'answered'};db.commit()
    else:payload['draft']={'selected_values':[{'malformed':'object'}]}
    response=client.post(f'/deferrals/project/{project.id}',json=payload)
    assert response.status_code in (409,422),response.text
    assert 'field:payment_methods' not in records(profile)


def test_compliance_details_are_required_for_new_question_but_not_for_saved_draft():
    question=build_next_question([{'field':'compliance_notes','label':'Compliance'}],final_prompt='Review')
    label='Financing disclaimer'
    assert label in question['detail_options']
    with pytest.raises(ValueError,match='exact text'):
        question_selection('compliance_notes',question,[label])
    assert question_selection('compliance_notes',question,[label],allow_incomplete=True)==[label]
    value=label+': Financing requires independent lender approval.'
    assert question_selection('compliance_notes',question,[value])==[value]
    standard='Use standard Company compliance; no Project-specific notes'
    assert question_selection('compliance_notes',question,[standard])==[standard]


def test_company_brand_is_not_legal_name_and_multiple_offices_are_not_headquarters():
    soup=BeautifulSoup('''<script type="application/ld+json">{"@type":"Organization","name":"Brand","legalName":"Brand Holdings LLC","address":{"streetAddress":"Office A"}}</script><script type="application/ld+json">{"@type":"Organization","name":"Brand","legalName":"Brand Holdings LLC","address":{"streetAddress":"Office B"}}</script>''','html.parser')
    facts=_structured_company_facts(soup)
    assert facts['official_company_name']=='Brand Holdings LLC'
    assert facts['preferred_display_name']=='Brand'
    assert 'headquarters' not in facts
    soup=BeautifulSoup('<h2>Regional offices</h2><address>Office A</address><address>Office B</address>','html.parser')
    assert 'headquarters' not in _structured_company_facts(soup)


def test_identical_brand_and_legal_name_does_not_offer_a_dba_copy():
    question=build_next_question([{'field':'dba','label':'DBA'}],final_prompt='Review',profile_data={'official_company_name':'Same','preferred_display_name':'Same'})
    assert not any(value.startswith('Yes') for value in question['options'])


@pytest.mark.parametrize('case,expected',[('confirmed',200),('no_channels',422),('unreviewed',409)])
def test_continue_public_presence_preserves_confirmed_channels_and_clears_resume_loop(api,case,expected):
    client,(db,company,user,project,profile,item)=api
    from app.modules.company_onboarding.router import router
    client.app.include_router(router,prefix='/company-onboarding')
    companies.get_or_create_session(db,company.id)
    owner=companies.get_or_create_profile(db,company.id)
    owner.profile_data={} if case=='no_channels' else {'public_contact_phones':['+13055550100']}
    owner.field_states={'public_contact_phones':{'status':'confirmed','applicable':True}} if case!='no_channels' else {}
    if case=='unreviewed':owner.profile_data['public_contact_emails']=['review@example.test']
    owner.field_sources={'__ui_deferrals__':{'enrichment':{'resumed':True,'deferred':False,'draft':{}}}}
    db.commit()
    response=client.post('/company-onboarding/public-presence/continue')
    assert response.status_code==expected,response.text
    if expected==200:
        assert owner.profile_data['public_contact_phones']==['+13055550100']
        assert owner.field_states['public_contact_phones']['status']=='confirmed'
        assert owner.field_states['public_contact_emails']['status']=='deferred'
        assert not records(owner)['enrichment']['resumed']
        assert not owner.final_approved
