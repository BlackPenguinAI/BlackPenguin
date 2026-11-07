from copy import deepcopy
from uuid import uuid4
import pytest
from pydantic import ValidationError
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects.detail_forms import DetailDecision,DeliveryEntry


def test_month_precision_and_scope_are_preserved_without_an_invented_day():
    decision=DetailDecision(field='delivery_dates',question_message_id='q',client_message_id=str(uuid4()),deliveries=[{'scope':'phase','reference':'North','timing':'2026-12'},{'scope':'unit','reference':'U001','timing':'2027-02-14'}])
    assert decision.formatted_value()=='Phase: North — December 2026\nUnit: U001 — February 14, 2027'


@pytest.mark.parametrize('scope,reference,timing',[('phase','','2026-12'),('unit','A','2026-13'),('project','North','2026-12'),('unit','A','2027-02-30'),('phase','A\nProject','2026-12')])
def test_invalid_scope_reference_or_date_cannot_be_confirmed(scope,reference,timing):
    with pytest.raises(ValidationError):DeliveryEntry(scope=scope,reference=reference,timing=timing)


def test_duplicate_delivery_scope_requires_clarification():
    decision=DetailDecision(field='delivery_dates',question_message_id='q',client_message_id=str(uuid4()),deliveries=[{'scope':'project','timing':'2026-12'},{'scope':'project','timing':'2027-01'}])
    with pytest.raises(ValueError,match='one delivery'):decision.formatted_value()


@pytest.mark.parametrize('field,task,details',[
    ('delivery_dates','delivery',{'deliveries':[{'scope':'property_type','reference':'Residence A','timing':'2026-12'}]}),
    ('parking_and_storage','parking',{'parking':{'applies_to':'Residence A','garage':'2-car garage included','storage':'Storage is optional'}}),
])
def test_detail_editor_saves_history_and_draft_revision_without_changing_published_data(api,field,task,details):
    client,(db,company,user,project,profile,item)=api
    before=deepcopy(profile.published_snapshot)
    opened=client.post(f'/projects/{project.id}/editor/{task}',json={'message':'Review '+task,'client_message_id':str(uuid4())})
    assert opened.status_code==200,opened.text
    question_id=opened.json()['message']['id']
    payload={'field':field,'question_message_id':question_id,'client_message_id':str(uuid4()),**details}
    response=client.post(f'/projects/{project.id}/details',json=payload)
    assert response.status_code==200,response.text
    assert profile.profile_data[field]
    assert profile.published_snapshot==before
    assert response.json()['message_saved']
    assert client.post(f'/projects/{project.id}/details',json=payload).status_code==200
    payload['client_message_id']=str(uuid4());payload['question_message_id']='stale-question'
    assert client.post(f'/projects/{project.id}/details',json=payload).status_code==409


def test_blank_parking_does_not_mean_no_parking():
    decision=DetailDecision(field='parking_and_storage',question_message_id='q',client_message_id=str(uuid4()),parking={'applies_to':'Project'})
    with pytest.raises(ValueError,match='at least one confirmed'):decision.formatted_value()


def test_detail_form_write_requires_manager_role(api):
    client,(db,company,user,project,profile,item)=api
    from app.modules.users.models import UserRole
    user.role=UserRole.SALES
    response=client.post(f'/projects/{project.id}/details',json={'field':'delivery_dates','question_message_id':'q','client_message_id':str(uuid4()),'deliveries':[{'scope':'project','timing':'2026-12'}]})
    assert response.status_code==403,response.text
