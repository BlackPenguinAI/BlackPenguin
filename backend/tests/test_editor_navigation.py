from copy import deepcopy
from uuid import uuid4
import pytest
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.projects.models import ProjectMessage
from app.modules.users.models import UserRole


def switch(client,project,target,source=None,revision=0,draft=None,changed=False,client_id=None):
    return client.post(f'/projects/{project.id}/editor/{target}',json={
        'message':'Open review: '+target,'client_message_id':client_id or str(uuid4()),
        'transition':{'from_task':source,'expected_navigation_revision':revision,'draft':draft or {},'changed':changed}})


def test_existing_unchanged_data_and_approval_are_preserved(api):
    client,(db,_,_,project,profile,item)=api
    before=(deepcopy(profile.profile_data),deepcopy(profile.published_snapshot),profile.draft_revision,profile.final_approved)
    assert switch(client,project,'catalog').status_code==200
    result=switch(client,project,'location','catalog',1)
    assert result.status_code==200,result.text
    bag=result.json()['profile']['ui_deferrals']
    assert not bag['field:property_type_catalog']['deferred']
    assert not bag['field:property_type_catalog']['resumed']
    assert bag['__editor_focus__']['draft']=={'active_task':'location','revision':2}
    db.refresh(profile)
    assert (profile.profile_data,profile.published_snapshot,profile.draft_revision,profile.final_approved)==before


def test_empty_section_is_deferred_and_modified_values_remain_unapproved_drafts(api):
    client,(db,_,_,project,profile,_)=api
    before=deepcopy(profile.profile_data)
    assert switch(client,project,'delivery').status_code==200
    result=switch(client,project,'parking','delivery',1)
    assert result.json()['profile']['ui_deferrals']['field:delivery_dates']['deferred']
    draft={'parking':{'garage':'Unconfirmed two spaces'}}
    result=switch(client,project,'location','parking',2,draft,True)
    assert result.status_code==200,result.text
    record=result.json()['profile']['ui_deferrals']['field:parking_and_storage']
    assert record['deferred'] and record['draft']==draft
    assert profile.profile_data==before
    result=switch(client,project,'parking','location',3)
    assert result.json()['profile']['ui_deferrals']['field:parking_and_storage']['draft']==draft
    result=switch(client,project,'team','parking',4)
    assert result.json()['profile']['ui_deferrals']['field:parking_and_storage']['deferred']


def test_meta_account_deferral_does_not_defer_campaigns(api):
    client,(_,_,_,project,_,_)=api
    assert switch(client,project,'meta_account').status_code==200
    result=switch(client,project,'meta_assets','meta_account',1)
    assert result.status_code==200,result.text
    records=result.json()['profile']['ui_deferrals']
    assert records['field:meta_connection_verified']['deferred']
    assert not records.get('field:campaigns_defined',{}).get('deferred',False)


def test_repeat_request_is_idempotent_and_stale_navigation_is_rejected(api):
    client,(db,_,_,project,profile,_)=api
    request_id=str(uuid4())
    first=switch(client,project,'catalog',client_id=request_id)
    assert first.status_code==200
    count=db.query(ProjectMessage).count()
    assert switch(client,project,'catalog',client_id=request_id).status_code==200
    assert db.query(ProjectMessage).count()==count
    before=deepcopy(profile.field_sources)
    result=switch(client,project,'location',revision=0)
    assert result.status_code==409
    db.refresh(profile);assert profile.field_sources==before


def test_failed_destination_rolls_back_previous_section_deferral(api):
    client,(db,_,user,project,profile,_)=api
    user.role=UserRole.MKT;db.commit()
    assert switch(client,project,'delivery').status_code==200
    before=deepcopy(profile.field_sources);count=db.query(ProjectMessage).count()
    assert switch(client,project,'team','delivery',1).status_code==403
    db.refresh(profile)
    assert profile.field_sources==before and db.query(ProjectMessage).count()==count


@pytest.mark.parametrize('draft',[{'access_token':'never-store'},{'nested':[{'password':'bad'}]},{'items':[{'id':'foreign-project-type'}]}])
def test_invalid_drafts_never_change_state(api,draft):
    client,(db,_,_,project,profile,_)=api
    assert switch(client,project,'catalog').status_code==200
    before=deepcopy(profile.field_sources)
    assert switch(client,project,'location','catalog',1,draft,True).status_code==422
    db.refresh(profile);assert profile.field_sources==before


def test_explicit_save_clears_pending_draft_without_affecting_other_sections(api):
    from app.modules.onboarding_deferrals import resolve_draft
    client,(db,_,_,project,profile,_)=api
    assert switch(client,project,'parking').status_code==200
    assert switch(client,project,'location','parking',1,{'parking':{'garage':'draft'}},True).status_code==200
    resolve_draft(profile,'field:parking_and_storage');db.commit()
    record=profile.field_sources['__ui_deferrals__']['field:parking_and_storage']
    assert not record['pending_draft'] and not record['deferred'] and record['draft']=={}


def test_previously_not_applicable_section_remains_resolved_on_navigation(api):
    client,(_,_,_,project,profile,_)=api
    assert profile.field_states['parking_and_storage']['status']=='not_applicable'
    assert switch(client,project,'parking').status_code==200
    result=switch(client,project,'location','parking',1)
    assert result.status_code==200
    assert not result.json()['profile']['ui_deferrals']['field:parking_and_storage']['deferred']
