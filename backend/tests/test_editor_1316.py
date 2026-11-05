"""Issues 13-16 regression probes with no external providers."""
from copy import deepcopy
from uuid import uuid4
import pytest
from test_catalog_789 import api
from test_onboarding_revisions_and_money import context
from app.modules.location_editor import router as location_router
from app.modules.projects import services
from app.modules.projects.models import ProjectMessage, SenderType
from app.modules.projects.editor_tasks import detect_task
from app.modules.sales_agent.intent_contract import normalize_intent

@pytest.mark.parametrize("task",["meta_account","meta_assets","team","catalog","documents","location","meta"])
def test_completed_project_reopens_task_without_erasing_or_unpublishing(api,task):
    client,(db,company,user,project,profile,item)=api
    old=deepcopy(profile.published_snapshot)
    original=services.save_message(db,project.session.id,SenderType.AI,"Old approved history")
    payload={"message":"Open review","client_message_id":str(uuid4())}
    result=client.post(f"/projects/{project.id}/editor/{task}",json=payload)
    assert result.status_code==200,result.text
    assert result.json()["next_question"]["task"]==task
    count=db.query(ProjectMessage).count()
    assert client.post(f"/projects/{project.id}/editor/{task}",json=payload).status_code==200
    assert db.query(ProjectMessage).count()==count
    state=client.get(f"/projects/{project.id}/chat/state")
    assert state.status_code==200,state.text
    assert state.json()["next_question"]["task"]==task
    db.refresh(original);db.refresh(profile)
    assert original.content=="Old approved history" and profile.published_snapshot==old and profile.final_approved

@pytest.mark.parametrize("text,task",[
 ("quiero actualizar meta","meta"),("quiero asociar campañas de Meta","meta_assets"),
 ("reconnect my Meta account","meta_account"),("quiero agregar unidades","catalog"),
 ("I want to upload documents","documents"),("actualizar ciudad y país","location"),
 ("I want to update Company users","team"),("Bank financing",None)])
def test_shared_task_parser(text,task):assert detect_task(text)==task

def test_location_is_selectable_suggested_and_only_published_on_approval(api):
    client,(db,company,user,project,profile,item)=api
    client.app.include_router(location_router,prefix="/editor")
    company.country_code="PE";db.commit()
    old_timezone=project.timezone
    url=f"/editor/project/{project.id}/location"
    options=client.get(url);assert options.status_code==200,options.text
    assert len(options.json()["countries"])>200
    assert any(c["city"]=="Miami" and c["country"]=="US" for c in options.json()["cities"])
    before=deepcopy(profile.published_snapshot)
    response=client.post(url,json={"country":"US","city":"Miami","timezone":"America/New_York"})
    assert response.status_code==200,response.text
    db.refresh(project);db.refresh(profile)
    assert project.timezone==old_timezone and profile.published_snapshot==before
    services.complete_onboarding(db,project,user.id)
    assert project.country=="US" and project.city=="Miami" and project.timezone=="America/New_York"

@pytest.mark.parametrize("body",[
 {"country":"US","city":"Miami","timezone":"America/Chicago"},
 {"country":"PE","city":"Lima","timezone":"America/New_York"},
 {"country":"US","city":"Miami","timezone":"UTC-5"},
 {"country":"XX","city":"Lima","timezone":"America/Lima"}])
def test_location_rejects_mismatch_without_changing_approved_data(api,body):
    client,(db,company,user,project,profile,item)=api
    client.app.include_router(location_router,prefix="/editor")
    before=deepcopy(profile.profile_data)
    response=client.post(f"/editor/project/{project.id}/location",json=body)
    assert response.status_code==422,response.text
    db.refresh(profile);assert profile.profile_data==before

@pytest.mark.parametrize("confidence",[None,True,"1",float("nan"),float("inf"),-1,2])
def test_no_fabricated_intent_confidence(confidence):
    value=normalize_intent({"primary_intent":"request_appointment","intent_confidence":confidence})
    assert value["intent_confidence"]==0 and value["requires_clarification"]

def test_mixed_intents_are_canonical_unique_and_entities_validated():
    value=normalize_intent({"primary_intent":"request_visual_material","intent_confidence":0.94,
      "secondary_intents":["request_document","request_document","invented"],"intent_entities":{"property_reference":{"company_id":"foreign"}}})
    assert value["secondary_intents"]==["request_document"]
    assert value["requires_clarification"] and "property_reference" not in value["intent_entities"]

def test_web_location_suggestion_is_not_approved_and_never_overwrites_confirmation(api):
    from app.modules.projects.models import ProjectOnboardingSource, ProjectOnboardingProposal, ProjectSourceKind, ProjectSourceStatus
    client,(db,company,user,project,profile,item)=api
    client.app.include_router(location_router,prefix="/editor")
    source=ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.URL,status=ProjectSourceStatus.READY,name="Project website",url="https://example.com/project")
    db.add(source);db.flush()
    db.add_all([ProjectOnboardingProposal(source_id=source.id,field_key="country",value="Mexico"),ProjectOnboardingProposal(source_id=source.id,field_key="city",value="Mexico City")]);db.commit()
    profile.field_states={**profile.field_states,"country":{"status":"missing"}}
    profile.profile_data={k:v for k,v in profile.profile_data.items() if k!="country"};db.commit()
    url=f"/editor/project/{project.id}/location"
    result=client.get(url);assert result.status_code==200,result.text
    assert result.json()["country"]=="MX" and result.json()["timezone"]=="America/Mexico_City"
    assert result.json()["source"]=="Project website"
    db.refresh(profile);assert profile.field_states["country"]["status"]=="missing"
    assert client.post(url,json={"country":"PE","city":"Lima","timezone":"America/Lima"}).status_code==200
    assert client.get(url).json()["country"]=="PE"

@pytest.mark.parametrize("scope",["project","company"])
def test_foreign_location_cannot_be_read_or_changed(api,scope):
    client,_=api;client.app.include_router(location_router,prefix="/editor")
    assert client.get(f"/editor/{scope}/foreign/location").status_code==404
    assert client.post(f"/editor/{scope}/foreign/location",json={"country":"PE","city":"Lima","timezone":"America/Lima"}).status_code==404

@pytest.mark.parametrize("text,task",[("I want to update Company users","team"),("quiero subir documentos","documents"),("actualizar ciudad y país","location")])
def test_company_editor_recognizes_task_before_field_answer_and_preserves_it(api,text,task):
    from app.modules.company_onboarding.router import router
    client,_=api;client.app.include_router(router,prefix="/company")
    response=client.post("/company/chat",json={"message":text})
    assert response.status_code==200,response.text
    assert response.json()["next_question"]["task"]==task
    state=client.get("/company/chat/state")
    assert state.status_code==200,state.text
    assert state.json()["next_question"]["task"]==task

def test_company_source_location_is_suggested_without_changing_company_country(api):
    from app.modules.company_onboarding.models import CompanyOnboardingSource,CompanyOnboardingProposal,SourceKind,SourceStatus
    client,(db,company,user,project,profile,item)=api
    client.app.include_router(location_router,prefix="/editor")
    company.country_code="PE"
    source=CompanyOnboardingSource(company_id=company.id,kind=SourceKind.OFFICIAL_WEBSITE,status=SourceStatus.READY,name="Company website",url="https://example.com/company")
    db.add(source);db.flush()
    db.add_all([CompanyOnboardingProposal(source_id=source.id,field_key="country",value="United States"),CompanyOnboardingProposal(source_id=source.id,field_key="city",value="Miami")]);db.commit()
    response=client.get(f"/editor/company/{company.id}/location")
    assert response.status_code==200,response.text
    assert response.json()["country"]=="US" and response.json()["timezone"]=="America/New_York"
    db.refresh(company);assert company.country_code=="PE"

def test_project_can_leave_editor_task_for_profile_review_without_approval(api):
    client,(db,company,user,project,profile,item)=api
    for task in ("location","review"):
        response=client.post(f"/projects/{project.id}/editor/{task}",json={"message":"Open "+task,"client_message_id":str(uuid4())})
        assert response.status_code==200,response.text
    assert response.json()["next_question"].get("task") is None
    assert profile.final_approved

def test_project_language_request_opens_same_task_before_consuming_previous_question(api):
    client,(db,company,user,project,profile,item)=api
    original=services.save_message(db,project.session.id,SenderType.AI,"Payment methods?",ui_payload={"field":"payment_methods","input_type":"text","label":"Payments","prompt":"Payment methods?"})
    response=client.post(f"/projects/{project.id}/chat",json={"message":"quiero actualizar meta","client_message_id":str(uuid4())})
    assert response.status_code==200,response.text
    assert response.json()["next_question"]["task"]=="meta"
    db.refresh(original);assert original.content=="Payment methods?" and original.response_payload["status"]=="superseded"

def test_generic_profile_edit_cannot_publish_a_city_timezone_mismatch(context):
    from fastapi import HTTPException
    db,company,user,project,profile,item=context
    published=deepcopy(profile.published_snapshot)
    services.apply_field_updates(db,profile,[services.user_field_update(k,v) for k,v in [("country","US"),("city","Miami"),("timezone","America/Chicago")]],allow_authoritative_statuses=True,actor_user_id=user.id)
    with pytest.raises(HTTPException) as error:services.complete_onboarding(db,project,user.id)
    assert error.value.status_code==422 and profile.published_snapshot==published

