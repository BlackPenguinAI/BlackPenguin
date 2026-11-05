"""Regression cases for the Sales turn coordinator, grounding and rendering."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from test_live_sales_agent import _db
from app.modules.companies.models import Company
from app.modules.projects.models import Project, ProjectProfile, ProjectPropertyType, ProjectUnit
from app.modules.sales_agent.models import AgentRun, SalesConversation, SalesMessage, OutboundMessage
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.response_policy import remove_unsolicited_appointment_offer
from app.modules.sales_agent.service import _offered_slot_selection
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.sales_agent.turn_context import appointment_execution_allowed, choice_index
from app.modules.sales_agent.response_policy import render_channel_text, split_channel_text, complete_requested_commercial_topics


@pytest.fixture
def case():
    db = _db()
    company = Company(name="Messaging Company"); db.add(company); db.flush()
    project = Project(company_id=company.id, name="Generic development", address="100 Main St", timezone="UTC")
    project.profile = ProjectProfile(profile_data={}, field_states={})
    db.add(project); db.flush()
    lead = Lead(company_id=company.id, project_id=project.id, full_name="Example lead", phone="+15550100001", source="manual", platform="manual", consent_status="granted")
    db.add(lead); db.flush()
    conversation = SalesConversation(company_id=company.id, project_id=project.id, lead_id=lead.id, channel="sms", provider="telnyx", provider_thread_key="turn-tests", is_paused=False)
    db.add(conversation); db.commit()
    yield db, company, project, lead, conversation
    db.close()


def outbound(db, conversation, content, metadata=None, seconds=0):
    message = SalesMessage(conversation_id=conversation.id, channel=conversation.channel, direction="outbound", role="assistant", content=content, status="delivered", metadata_json=metadata or {}, created_at=datetime.utcnow()+timedelta(seconds=seconds))
    db.add(message); db.commit()
    return message


def offer_slot(db, conversation):
    slot = datetime.utcnow()+timedelta(days=2)
    slot = slot.replace(hour=15, minute=0, second=0, microsecond=0)
    outbound(db, conversation, "I found verified appointment times: 3:00 PM.", {"appointment_offer":{"slots":[slot.isoformat()]}})
    return slot


def test_property_choice_cannot_book_an_old_appointment_offer(case):
    db, company, project, lead, conversation = case
    offer_slot(db, conversation)
    outbound(db, conversation, "1. Studio\n\n2. Loft", {"property_catalog_offer":{"property_type_ids":["studio","loft"]}}, seconds=1)
    assert _offered_slot_selection(db, conversation_id=conversation.id, inbound_text="The first option", project=project, now=datetime.utcnow()) is None


def test_manual_response_supersedes_an_older_ai_offer(case):
    db,company,project,lead,conversation=case
    offer_slot(db,conversation)
    human=outbound(db,conversation,"Which property interests you?",seconds=1)
    human.role="human";db.commit()
    assert _offered_slot_selection(db,conversation_id=conversation.id,inbound_text="The first option",project=project,now=datetime.utcnow()) is None


@pytest.mark.parametrize("text", ["Can you send pictures of the first option?", "No, not the first appointment; I want a brochure", "Photos of option 1 at 3 PM please"])
def test_a_new_material_request_is_not_slot_consent(case, text):
    db, company, project, lead, conversation = case
    offer_slot(db, conversation)
    assert _offered_slot_selection(db, conversation_id=conversation.id, inbound_text=text, project=project, now=datetime.utcnow()) is None


def test_removing_visit_offer_preserves_list_and_paragraph_boundaries():
    value = "Confirmed types:\n\n1. Studio\n42 m².\n\n2. Loft\n80 m².\n\nWould you like to schedule a visit?"
    assert remove_unsolicited_appointment_offer(value) == "Confirmed types:\n\n1. Studio\n42 m².\n\n2. Loft\n80 m²."


def test_individual_inventory_does_not_leak_obsolete_type_quantities(case):
    db, company, project, lead, conversation = case
    product = ProjectPropertyType(project=project, name="Studio", bedrooms=0, available_units=99, review_status="confirmed", inventory_updated_at=datetime.utcnow()-timedelta(days=1))
    db.add(product); db.flush()
    db.add_all([ProjectUnit(project=project, unit_code="A", typology="Studio", status="available", inventory_updated_at=datetime.utcnow()-timedelta(days=1)), ProjectUnit(project=project, unit_code="B", typology="Studio", status="sold", inventory_updated_at=datetime.utcnow()-timedelta(days=1))]); db.commit()
    context = build_commercial_context(db, project=project, company_id=company.id, lead_id=lead.id)
    assert context["property_types"][0]["available_units"] == 1
    assert context["catalog_coverage"]["exhaustive"] is False


@pytest.mark.parametrize("confidence", [None, True, False, -1, 2, float("nan"), .1, .79])
def test_untrusted_intent_never_authorizes_scheduling(confidence):
    assert not appointment_execution_allowed({"primary_intent":"request_appointment", "intent_confidence":confidence})


@pytest.mark.parametrize("flag", ["requires_clarification", "policy_violations"])
def test_clarification_or_policy_blocks_appointment_execution(flag):
    assert not appointment_execution_allowed({"primary_intent":"request_appointment", "intent_confidence":.99, flag:True})


def test_secondary_appointment_is_supported_but_human_request_is_not_overridden():
    result = {"primary_intent":"request_pricing", "secondary_intents":["request_appointment"], "intent_confidence":.95}
    assert appointment_execution_allowed(result)
    result["secondary_intents"].append("human_requested")
    assert not appointment_execution_allowed(result)


@pytest.mark.parametrize("text,index", [("1",0),("option 7",6),("The second option",1),("0",None),("send photos of option 2",None),("the second property, not the visit",None)])
def test_numeric_choice_must_be_a_bounded_selection(text,index):
    assert choice_index(text)==index


def model_turn(case, text, *, primary="general_question", secondary=(), reply="Here is the information.", confidence=.95, entities=None, actions=None):
    import json
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.sales_agent.graph import build_sales_graph
    db, company, project, lead, conversation = case
    if not db.query(AIConfiguration).filter_by(company_id=company.id).first():
        db.add(AIConfiguration(company_id=company.id, openrouter_api_key="test-only", agent_ventas={"model":"test/model"}))
    db.add(SalesMessage(conversation_id=conversation.id, channel="sms", direction="inbound", role="user", content=text, status="received")); db.commit()
    payload = {"reply":reply,"primary_intent":primary,"secondary_intents":list(secondary),"intent_confidence":confidence,
               "intent_entities":entities or {},"requires_clarification":False,"proposed_actions":actions or [],"requires_human":False}
    with patch("app.modules.sales_agent.graph.generate_llm_response", new=AsyncMock(return_value=json.dumps(payload))) as model:
        result=asyncio.run(build_sales_graph(db).ainvoke({"event_id":"unit-turn","mode":"live","conversation_id":conversation.id,"company_id":company.id,"project_id":project.id,"lead_id":lead.id,"channel":"sms","inbound_text":text,"policy_violations":[],"requires_human":False}))
    return result, model


def test_published_facts_win_over_unapproved_changes_and_model_claims(case):
    from app.modules import onboarding_versions as versions
    db, company, project, lead, conversation = case
    profile=project.profile
    profile.profile_data={"payment_methods":["Bank financing"],"amenities":["Garden"]}
    profile.field_states={key:{"status":"confirmed","applicable":True} for key in profile.profile_data}
    db.commit();profile.published_snapshot={**versions.snapshot(profile,db),"revision":7};db.commit()
    profile.profile_data={"payment_methods":["Cash only"],"amenities":["Unapproved pool"]};db.commit()
    result, model=model_turn(case,"What borrowing choices and features can I get?", primary="request_financing",secondary=["request_amenities"], reply="Cash only. There is a pool.")
    assert "Bank financing" in result["proposed_reply"] and "Garden" in result["proposed_reply"]
    assert "Cash only" not in result["proposed_reply"] and "pool" not in result["proposed_reply"]
    assert result["commercial_context"]["fact_provenance"]["payment_methods"]["approved_revision"]==7
    request=model.await_args.args[2]
    assert any("active_offer_kind" in item["content"] for item in request)


def test_catalog_is_not_an_exhaustive_denial_and_numbers_map_to_offered_ids(case):
    db, company, project, lead, conversation=case
    first=ProjectPropertyType(project=project,name="Studio",bedrooms=0,review_status="confirmed",sort_order=0)
    fifth=ProjectPropertyType(project=project,name="Family home",bedrooms=5,review_status="confirmed",sort_order=1)
    db.add_all([first,fifth]);db.commit()
    result,_=model_turn(case,"Do you have larger homes?",primary="request_property_catalog",reply="Only studios exist. No larger homes exist.")
    assert "Family home" in result["proposed_reply"] and "Only studios" not in result["proposed_reply"]
    assert "other options have not been ruled out" in result["proposed_reply"]
    outbound(db,conversation,result["proposed_reply"],{"property_catalog_offer":result["property_catalog_offer"]})
    first.sort_order=5;fifth.sort_order=0;db.commit()
    selected,_=model_turn(case,"1",primary="request_property_details")
    assert selected["proposed_reply"].startswith("Here are the confirmed details for Studio")
    assert "Family home" not in selected["proposed_reply"]


def test_unbound_number_requires_clarification_instead_of_catalog_or_booking(case):
    result,_=model_turn(case,"2",primary="request_property_details")
    assert result["requires_clarification"] and "refer to a property type" in result["proposed_reply"]
    assert not appointment_execution_allowed(result)


def run_live(case,text,result):
    from app.modules.sales_agent.live_service import process_live_inbound
    db,company,project,lead,conversation=case
    ids=(conversation.id,lead.id,project.id)
    message=SalesMessage(conversation_id=conversation.id,channel="sms",direction="inbound",role="user",content=text,status="received")
    db.add(message);db.commit();message_id=message.id
    graph=AsyncMock();graph.ainvoke.return_value={"proposed_reply":"Approved information.","proposed_actions":[],"policy_violations":[],"requires_human":False,"error_code":None,**result}
    with patch("app.modules.sales_agent.live_service.SessionLocal",return_value=db),patch("app.modules.sales_agent.live_service.build_sales_graph",return_value=graph),patch("app.modules.sales_agent.live_service._dispatch",new=AsyncMock(return_value=SalesMessage())) as dispatch,patch("app.modules.sales_agent.live_service._schedule_next_action"),patch("app.modules.sales_agent.service.available_slots",return_value=[]) as slots:
        asyncio.run(process_live_inbound(ids[0],message_id))
    return dispatch,slots,graph,ids


def test_pending_location_does_not_preempt_a_mixed_material_and_financing_request(case):
    db,company,project,lead,conversation=case
    lead.meta_form_data={"pending_location_request":"Visit next Monday"};db.commit()
    outbound(db,conversation,"Which location?",{"proposed_actions":[{"type":"request_visit_location"}],"location_offer":{"pending":True}})
    dispatch,slots,graph,ids=run_live(case,"Send photos and explain financing.",{
        "primary_intent":"request_visual_material","secondary_intents":["request_financing"],"intent_confidence":.99,
        "commercial_context":{},"proposed_reply":"Payment and financing: Bank financing."})
    graph.ainvoke.assert_awaited_once();slots.assert_not_called()
    reply=dispatch.await_args.kwargs["content"]
    assert "Bank financing" in reply and "approved file" in reply
    assert db.query(Lead).filter_by(id=ids[1]).one().meta_form_data["pending_location_request"]=="Visit next Monday"
    assert db.query(Meeting).count()==0


@pytest.mark.parametrize("confidence,clarification",[(.1,False),(.99,True),(None,False)])
def test_live_low_confidence_appointment_cannot_bypass_graph_clarification(case,confidence,clarification):
    dispatch,slots,graph,ids=run_live(case,"Visit, perhaps?",{"primary_intent":"request_appointment","intent_confidence":confidence,"requires_clarification":clarification,"proposed_reply":"Please clarify your preferred next step."})
    slots.assert_not_called()
    assert "clarify" in dispatch.await_args.kwargs["content"]


def test_secondary_visit_keeps_textual_answers_in_the_same_reply(case):
    dispatch,slots,graph,ids=run_live(case,"What is the financing and can I schedule a visit?",{
        "primary_intent":"request_financing","secondary_intents":["request_appointment"],"intent_confidence":.99,
        "proposed_reply":"Payment and financing: Bank financing."})
    assert "Bank financing" in dispatch.await_args.kwargs["content"]
    assert "verified appointment time" in dispatch.await_args.kwargs["content"]
    slots.assert_called_once()


@pytest.mark.parametrize("channel",["sms","whatsapp"])
def test_lossless_renderer_and_block_split_preserve_all_options_and_urls(channel):
    url="https://example.com/resources/"+"a"*180
    raw="Confirmed types: 1. Studio\n42 m². 2. Loft\n80 m².\n\n"+"\n\n".join(f"{i}. Layout {i}\nA short confirmed summary for this property. "*2 for i in range(3,70))+"\n\nResources:\n"+url
    rendered=render_channel_text(raw,channel)
    assert "types:\n\n1. Studio" in rendered and "\n\n2. Loft" in rendered
    parts=split_channel_text(rendered,channel)
    assert len(parts)>1
    assert url in parts[-1]
    for i in range(3,70):assert f"{i}. Layout {i}" in "\n".join(parts)
    assert all(len(p)<=(1400 if channel=="sms" else 3500) for p in parts)
    import re
    assert re.sub(r"\s+"," "," ".join(parts))==re.sub(r"\s+"," ",rendered)


def test_opaque_url_tokens_are_not_changed_by_markdown_cleanup():
    url="https://example.com/resources/__token__?key=__secret__"
    assert render_channel_text("**Resources**\n"+url)=="Resources\n"+url


def test_price_completion_keeps_currencies_separate_and_inventory_partial_explicit():
    reply,_=complete_requested_commercial_topics("",inbound="Prices and availability?",actions=[],commercial={"inventory_source":"property_type_catalog","inventory":[{"starting_price":30000,"currency":"USD","available_units":0,"inventory_updated_at":"2026-01-01"},{"starting_price":500000,"currency":"MXN","available_units":None}]})
    assert "USD 30,000" in reply and "MXN 500,000" in reply
    assert "Verified subtotal: 0 homes" in reply and "remaining records is not confirmed" in reply


def approved_asset(case, tags, *, name="Generic sales file", links=None, asset_type="brochure"):
    from app.modules.projects.models import ProjectSalesAsset, ProjectOnboardingSource, ProjectSourceKind, ProjectSourceStatus
    db,company,project,lead,conversation=case
    source=ProjectOnboardingSource(project_id=project.id,kind=ProjectSourceKind.UPLOADED_FILE,status=ProjectSourceStatus.READY,name=name+".pdf",mime_type="application/pdf",storage_path="test/never-read.pdf",extracted_links=links or [])
    db.add(source);db.flush()
    asset=ProjectSalesAsset(company_id=company.id,project_id=project.id,source_id=source.id,asset_type=asset_type,content_tags=tags,display_name=name,approval_status="approved",approved_at=datetime.utcnow(),allowed_channels=["sms","whatsapp"])
    db.add(asset);db.commit()
    return asset


def execute_material(case,text,reply="The confirmed amenities include a garden.",result=None):
    from app.modules.sales_agent.live_service import _execute_share_actions
    db,company,project,lead,conversation=case
    commercial=build_commercial_context(db,project=project,company_id=company.id,lead_id=lead.id,channel=conversation.channel)
    offer={}
    response=_execute_share_actions(db,conversation=conversation,lead=lead,run=SimpleNamespace(id=None),reply=reply,actions=[],commercial=commercial,inbound_text=text,intent_result=result,offer_metadata=offer)
    return response,offer


def test_explicit_mixed_request_shares_all_partial_matches_without_five_file_cap(case):
    from app.modules.projects.models import SalesAssetShare
    db,company,project,lead,conversation=case
    for number in range(7):approved_asset(case,["floor_plan"],name=f"Layout pack {number}")
    (reply,actions,shares),offer=execute_material(case,"Please send floor plans and a price list. What amenities are there?")
    assert len(shares)==7 and len([a for a in actions if a["type"]=="share_asset"])==7
    assert "garden" in reply and "price list" in reply and "floor plan" in reply
    assert reply.index("garden")<reply.index("/projects/a/")
    assert not offer
    assert db.query(SalesAssetShare).count()==7
    assert all(f"Layout pack {i}: http" in reply for i in range(7))


def test_360_is_shared_as_an_audited_link_and_unrequested_map_is_not(case):
    from app.modules.projects.models import SalesAssetShare
    approved_asset(case,["brochure","virtual_tour"],links=[{"url":"https://my.matterport.com/show/?m=genericTour","kind":"virtual_tour","label":"Interactive tour"},{"url":"https://maps.example.com/place","kind":"location_map","label":"Map"}])
    (reply,actions,shares),_=execute_material(case,"Send the 360 virtual tour please.")
    db,*_=case
    targets=[row.target_url for row in db.query(SalesAssetShare).all()]
    assert "https://my.matterport.com/show/?m=genericTour" in targets
    assert "https://maps.example.com/place" not in targets
    assert "Interactive tour: http" in reply


def test_model_material_entities_work_without_exact_keyword_phrase(case):
    approved_asset(case,["gallery_image"],name="Approved interior views")
    (reply,actions,shares),_=execute_material(case,"I would like a peek at the interiors.",result={"primary_intent":"request_visual_material","intent_entities":{"requested_materials":["gallery_image"]}})
    assert shares and "Approved interior views: http" in reply


def test_generic_material_offer_keeps_text_and_sends_all_offered_files_only_after_consent(case):
    approved_asset(case,["floor_plan"],name="Plan A");approved_asset(case,["floor_plan"],name="Plan B")
    (reply,actions,shares),offer=execute_material(case,"Do you have floor plans?")
    assert "garden" in reply and "Would you like me to send" in reply and not shares
    db,company,project,lead,conversation=case
    outbound(db,conversation,reply,{"material_offer":offer})
    (reply,actions,shares),_=execute_material(case,"Yes, please")
    assert len(shares)==2 and "Plan A: http" in reply and "Plan B: http" in reply


def test_stale_material_offer_does_not_treat_yes_after_another_question_as_consent(case):
    asset=approved_asset(case,["floor_plan"])
    db,company,project,lead,conversation=case
    conversation.pending_asset_id=asset.id;db.commit()
    outbound(db,conversation,"Which property would you like?",{"property_catalog_offer":{"property_type_ids":["studio"]}})
    (_,actions,shares),_=execute_material(case,"Yes")
    assert not shares and not actions


@pytest.mark.parametrize("state",["draft","expired","wrong_channel","revoked_during_turn"])
def test_unapproved_or_expired_material_is_not_exposed_even_from_stale_context(case,state):
    from app.modules.sales_agent.live_service import _execute_share_actions
    asset=approved_asset(case,["floor_plan"],name="Not permitted")
    db,company,project,lead,conversation=case
    commercial=build_commercial_context(db,project=project,company_id=company.id,lead_id=lead.id)
    if state in {"draft","revoked_during_turn"}:asset.approval_status="draft"
    elif state=="expired":asset.valid_until=datetime.utcnow()-timedelta(seconds=1)
    else:asset.allowed_channels=["whatsapp"]
    db.commit()
    reply,actions,shares=_execute_share_actions(db,conversation=conversation,lead=lead,run=SimpleNamespace(id=None),reply="Here is the information.",actions=[],commercial=commercial,inbound_text="Send floor plans.")
    assert not shares and "Not permitted" not in reply and "/projects/a/" not in reply


def test_pdf_with_images_can_answer_photos_without_false_refusal_or_email_promise(case):
    approved_asset(case,["brochure","gallery_image"],name="Mixed content PDF")
    (reply,actions,shares),_=execute_material(case,"Can I see photos and get the brochure by email?",reply="The garden is confirmed. I can't provide the images. I will send the brochure via email.")
    assert shares and "Mixed content PDF: http" in reply and "garden is confirmed" in reply
    assert "can't provide" not in reply and "will send" not in reply
    assert "no email has been sent" in reply


def test_missing_photos_can_offer_an_approved_brochure_without_claiming_it_has_photos(case):
    approved_asset(case,["brochure","floor_plan"],name="Plans overview")
    (reply,actions,shares),offer=execute_material(case,"Can I see photos?")
    assert not shares and offer and "Would you like that link" in reply
    assert "containing brochure, floor plan" in reply


@pytest.mark.parametrize("channel",["sms","whatsapp"])
def test_transport_sends_every_block_once_and_preserves_full_run_reply(case,channel):
    from app.modules.sales_agent.live_service import _dispatch
    db,company,project,lead,conversation=case
    conversation.channel=channel
    db.add(SalesMessage(conversation_id=conversation.id,channel=channel,direction="inbound",role="user",content="Tell me the options",status="received"))
    run=AgentRun(conversation_id=conversation.id,event_id="chunk-test",mode="live",status="completed",graph_version="test",toolset_version="test",model="test/model",prompt_snapshot={},input_snapshot={},output_snapshot={})
    db.add(run);db.commit()
    raw="All confirmed layouts:\n\n"+"\n\n".join(f"{index}. Layout {index}\n"+"A confirmed summary. "*9 for index in range(1,40))
    sender=AsyncMock(side_effect=lambda *args,**kwargs:{"sid":f"provider-{sender.await_count}","status":"queued"})
    with patch("app.modules.sales_agent.live_service.send_sms",sender),patch("app.modules.sales_agent.live_service.send_message",sender):
        for _ in range(2):asyncio.run(_dispatch(db,conversation=conversation,lead=lead,content=raw,role="assistant",agent_run_id=run.id,metadata={"event_kind":"agent_reply"}))
    parts=split_channel_text(raw,channel)
    assert sender.await_count==len(parts)
    assert db.query(OutboundMessage).count()==len(parts)
    assert db.query(SalesMessage).filter_by(direction="outbound").count()==len(parts)
    db.refresh(run)
    assert run.output_snapshot["reply"]==render_channel_text(raw,channel)
    assert len(run.output_snapshot["delivery_parts"])==len(parts)
    bodies=[call.kwargs.get("body") for call in sender.await_args_list]
    assert bodies==parts


def test_same_time_on_two_days_requires_date_and_offset_is_preserved(case):
    db,company,project,lead,conversation=case
    slot=datetime.utcnow().replace(hour=15,minute=0,second=0,microsecond=0)+timedelta(days=2)
    outbound(db,conversation,"Choose a verified time",{"appointment_offer":{"slots":[slot.isoformat(),(slot+timedelta(days=1)).isoformat()]}})
    assert _offered_slot_selection(db,conversation_id=conversation.id,inbound_text="3 PM",project=project,now=datetime.utcnow()) is None
    assert _offered_slot_selection(db,conversation_id=conversation.id,inbound_text=f"{slot.date().isoformat()} at 3 PM",project=project,now=datetime.utcnow())==slot


def test_mixed_slot_and_material_request_is_resolved_only_after_classification(case):
    from app.modules.sales_agent.service import _classified_slot_selection
    db,company,project,lead,conversation=case
    slot=offer_slot(db,conversation)
    result={"primary_intent":"request_document","secondary_intents":["select_appointment_slot"],"intent_confidence":.95}
    selected=_classified_slot_selection(db,conversation=conversation,project=project,inbound_text="The first appointment and send the brochure please",result=result,now=datetime.utcnow())
    assert selected==slot
    result["requires_clarification"]=True
    assert _classified_slot_selection(db,conversation=conversation,project=project,inbound_text="The first appointment and send the brochure please",result=result,now=datetime.utcnow()) is None


@pytest.mark.parametrize("text",["Photos of the first option please", "Pictures of the unit at 3 PM please"])
def test_material_request_is_not_booking_even_with_a_wrong_high_confidence_slot_label(case,text):
    from app.modules.sales_agent.service import _classified_slot_selection
    db,company,project,lead,conversation=case
    offer_slot(db,conversation)
    result={"primary_intent":"select_appointment_slot","secondary_intents":["request_visual_material"],"intent_confidence":.99}
    assert _classified_slot_selection(db,conversation=conversation,project=project,inbound_text=text,result=result,now=datetime.utcnow()) is None


def test_explicit_resumption_preserves_the_original_pending_location_date(case):
    from app.modules.sales_agent.service import _confirm_or_request_location
    db,company,project,lead,conversation=case
    project.profile.profile_data={"exact_address":[{"label":"North","address":"1 North St"},{"label":"South","address":"2 South St"}]}
    lead.meta_form_data={"pending_location_request":"Visit next Monday"};db.commit()
    ready,question,resume=_confirm_or_request_location(project,lead,"Let's resume my visit")
    assert not ready and "1. North" in question and "\n\n2. South" in question
    assert lead.meta_form_data["pending_location_request"]=="Visit next Monday"
    ready,question,resume=_confirm_or_request_location(project,lead,"2")
    assert ready and resume=="Visit next Monday" and lead.meta_form_data["selected_visit_location"]["label"]=="South"


def test_partial_delivery_retry_does_not_resend_successful_blocks(case):
    from app.modules.sales_agent.live_service import _dispatch
    db,company,project,lead,conversation=case
    run=AgentRun(conversation_id=conversation.id,event_id="partial-retry",mode="live",status="completed",graph_version="test",toolset_version="test",model="test/model",prompt_snapshot={},input_snapshot={},output_snapshot={})
    db.add(run);db.commit()
    raw="\n\n".join(f"{i}. Option {i}\n"+"Verified descriptive information. "*20 for i in range(1,12))
    calls=[]
    async def send(*args,**kwargs):
        calls.append(kwargs["body"])
        if len(calls)==2:raise RuntimeError("simulated provider failure")
        return {"sid":f"msg-{len(calls)}","status":"queued"}
    with patch("app.modules.sales_agent.live_service.send_sms",side_effect=send):
        with pytest.raises(RuntimeError):asyncio.run(_dispatch(db,conversation=conversation,lead=lead,content=raw,role="assistant",agent_run_id=run.id))
        assert db.query(OutboundMessage).filter_by(status="failed").count()==1
        asyncio.run(_dispatch(db,conversation=conversation,lead=lead,content=raw,role="assistant",agent_run_id=run.id))
    parts=split_channel_text(raw)
    assert calls.count(parts[0])==1 and calls.count(parts[1])==2
    assert db.query(OutboundMessage).count()==len(parts)
    assert db.query(SalesMessage).filter_by(status="failed").count()==0
