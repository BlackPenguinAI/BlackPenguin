"""Request attribution and protected escalation regression cases."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import asyncio
import pytest
from test_sales_turn_1720 import case, model_turn, run_live, outbound
from app.modules.projects.models import ProjectPropertyType
from app.modules.sales_agent.models import SalesConversation, SalesFollowUpJob
from app.modules.sales_crm.models import Lead
from app.modules.governance.models import HumanInterventionCase
from app.modules.sales_agent.escalation_policy import apply_escalation_policy


@pytest.mark.parametrize("previous,inbound",[
    ("You may need legal advice for that.","You said I need legal advice, but I just want the approved brochure."),
    ("You could ask about a special discount.","You said I should ask for a special discount; I am only asking for the approved price list."),
])
def test_quoted_previous_advice_is_not_a_new_legal_or_exception_request(case,previous,inbound):
    db,company,project,lead,conversation=case
    outbound(db,conversation,previous)
    dispatch,slots,graph,ids=run_live(case,inbound,{"primary_intent":"request_document","intent_confidence":.99,
        "proposed_reply":"I can help with the approved materials."})
    details={"paused":db.get(SalesConversation,ids[0]).is_paused,
        "reason":db.query(HumanInterventionCase).one().reason if db.query(HumanInterventionCase).count() else None,
        "graph_invocations":graph.ainvoke.await_count,"reply":dispatch.await_args.kwargs["content"]}
    print(details)
    assert not details["paused"], details
    assert db.query(HumanInterventionCase).count()==0
    graph.ainvoke.assert_awaited_once()


def test_ambiguous_opt_out_then_literal_stop_persists_real_unsubscribe(case):
    db,company,project,lead,conversation=case
    ids=(company.id,project.id,lead.id,conversation.id)
    dispatch,slots,graph,_=run_live(case,"Maybe stop those offers?",{
        "primary_intent":"opt_out","intent_confidence":.3,"proposed_reply":"You have been unsubscribed.","proposed_actions":[]})
    assert "have been unsubscribed" not in dispatch.await_args.kwargs["content"]
    assert not db.get(Lead,ids[2]).is_opt_out
    newcase=(db,db.get(type(company),ids[0]),db.get(type(project),ids[1]),db.get(Lead,ids[2]),db.get(SalesConversation,ids[3]))
    dispatch,slots,graph,_=run_live(newcase,"STOP",{})
    graph.ainvoke.assert_not_called()
    assert db.get(Lead,ids[2]).is_opt_out
    assert db.get(Lead,ids[2]).consent_status=="opted_out"
    assert "unsubscribed" in dispatch.await_args.kwargs["content"]


def test_cancelled_followup_cannot_dispatch_after_consent_clarification(case):
    from app.modules.sales_agent.live_service import process_live_followup_job
    db,company,project,lead,conversation=case
    job=SalesFollowUpJob(conversation_id=conversation.id,status="processing",scheduled_at=datetime.utcnow(),reason="test",idempotency_key="reverify-consent")
    db.add(job);db.commit();job_id=job.id
    run_live(case,"Maybe stop those offers?",{"primary_intent":"opt_out","intent_confidence":.3,"proposed_reply":"You have been unsubscribed."})
    assert db.get(SalesFollowUpJob,job_id).status=="cancelled"
    graph=AsyncMock()
    with patch("app.modules.sales_agent.live_service.SessionLocal",return_value=db),patch("app.modules.sales_agent.live_service.build_sales_graph",return_value=graph),patch("app.modules.sales_agent.live_service._dispatch",new=AsyncMock()) as dispatch:
        asyncio.run(process_live_followup_job(job_id))
    graph.ainvoke.assert_not_awaited();dispatch.assert_not_awaited()


def test_both_matching_staff_rules_remain_visible_in_trace():
    result=apply_escalation_policy({"primary_intent":"request_document","intent_confidence":.2,"requires_clarification":True,
        "proposed_reply":"Please clarify which file.","proposed_actions":[],"commercial_context":{}},
        inbound="Those documents, maybe?",routing={"pause_on_low_confidence":True,"pause_on_missing_material":True})
    decision=result["escalation_decision"]
    assert decision["matched_pause_rules"]==["LOW_CONFIDENCE","MISSING_MATERIAL"]
    assert decision["disposition"]=="pause" and decision["reason"]=="LOW_CONFIDENCE"
    assert result["response_policy_trace"]["escalation"]==decision


def test_consent_clarification_cannot_share_or_schedule_other_model_actions():
    result=apply_escalation_policy({"primary_intent":"opt_out","intent_confidence":.4,
        "proposed_reply":"You have been unsubscribed.","commercial_context":{"available_assets":[{"asset_id":"approved"}]},
        "proposed_actions":[{"type":"share_asset","asset_id":"approved"},{"type":"request_available_slots"}]},inbound="Maybe stop these offers?")
    assert result["requires_clarification"]
    assert result["proposed_actions"]==[{"type":"ask_qualification_question"}]
    assert result["escalation_decision"]["consent_clarification_required"]


def test_correction_reads_current_price_for_the_previously_selected_property(case):
    db,company,project,lead,conversation=case
    product=ProjectPropertyType(project=project,name="Corner residence",bedrooms=3,starting_price=450000,currency="USD",review_status="confirmed")
    other=ProjectPropertyType(project=project,name="Garden studio",bedrooms=0,starting_price=150000,currency="USD",review_status="confirmed")
    db.add_all([product,other]);db.commit()
    outbound(db,conversation,"Corner residence starts at 400,000 USD.",{"selected_property_type_id":product.id})
    result,_=model_turn(case,"That is wrong. Please check the price you gave me.",primary="request_pricing",reply="I apologize for the oversight. Corner residence is 400,000 USD.")
    assert "450,000 USD" in result["proposed_reply"] and "400,000 USD" not in result["proposed_reply"]
    assert "Garden studio" not in result["proposed_reply"]
    assert result["response_policy_trace"]["correction"]["previous_monetary_validation"]["replaced"]


def test_unknown_option_reference_cannot_replace_the_existing_selection(case):
    db,company,project,lead,conversation=case
    product=ProjectPropertyType(project=project,name="Courtyard home",bedrooms=2,review_status="confirmed")
    db.add(product);db.commit()
    outbound(db,conversation,"1. Courtyard home",{"property_catalog_offer":{"property_type_ids":[product.id]}})
    outbound(db,conversation,"Courtyard home details.",{"selected_property_type_id":product.id})
    result,_=model_turn(case,"I meant option 99, not a visit.",primary="request_property_details",entities={"property_reference":"option 99","correction_requested":True})
    assert result["requires_clarification"]
    assert result["selected_property_type_id"]==product.id
    assert not result["response_policy_trace"]["appointment_intent"]


@pytest.mark.parametrize("text",[
    'You said "I need legal advice". Please send the brochure instead.',
    'You mentioned “ask for a special discount”; I only want the approved price list.',
    "Dijiste que necesito asesoría legal, pero solo quiero el brochure.",
    "El agente dijo que podría negociar, sin embargo solo quiero los precios aprobados.",
    "The assistant suggested talking to a human; I only want the floor plans.",
    "Tú sugeriste hablar con un asesor; solo quiero el PDF.",
    '“You said I need legal advice”, but I only want the brochure.',
    '"Earlier you mentioned a special discount"; I only want the standard price list.',
])
def test_attributed_reference_is_not_a_deterministic_handoff(text):
    from app.modules.governance.services import escalation_reason,request_attribution
    assert escalation_reason(text) is None
    assert request_attribution(text)["reported_spans"]


@pytest.mark.parametrize("text",[
    "The AI wrote that I need legal advice, but I only want the brochure.",
    "You claimed I should ask for a special discount; I only want the standard price list.",
    "If I needed legal advice, would the brochure help?",
    "Can you not give me legal advice? Just send the brochure.",
    "Please send the brochure, the AI wrote that I need legal advice.",
    "Please send the brochure and the AI claimed I should ask for a special discount.",
])
def test_other_reports_and_ambiguous_mentions_reach_the_classifier(text):
    from app.modules.governance.services import escalation_reason
    assert escalation_reason(text) is None


@pytest.mark.parametrize("text,reason",[
    ('You said "ask for a brochure", but I need legal advice.',"LEGAL_QUESTION"),
    ('You said "I need legal advice", and I need a lawyer now.',"LEGAL_QUESTION"),
    ('You mentioned a brochure, now I want to negotiate a special discount.',"COMPLEX_NEGOTIATION"),
    ("You mentioned a brochure and I want custom terms.","COMPLEX_NEGOTIATION"),
    ("Dijiste que podía pedir un brochure, pero necesito asesoría legal.","LEGAL_QUESTION"),
    ("El agente dijo que hay brochure y necesito negociar una excepción.","COMPLEX_NEGOTIATION"),
    ('I need "legal advice".',"LEGAL_QUESTION"),
    ('I want a "special discount".',"COMPLEX_NEGOTIATION"),
    ('"I need legal advice, as you said."',"LEGAL_QUESTION"),
    ("As you said, I need legal advice.","LEGAL_QUESTION"),
    ("I need legal advice, as you said earlier.","LEGAL_QUESTION"),
    ('You said "contact Sales", but please transfer me to a person.',"HUMAN_REQUESTED"),
])
def test_attribution_never_hides_a_separate_affirmative_request(text,reason):
    from app.modules.governance.services import escalation_reason
    assert escalation_reason(text)==reason


def test_attribution_keeps_raw_text_and_offsets_without_overwriting_evidence():
    from app.modules.governance.services import request_attribution
    text='You said "please ask a lawyer", but I only need the brochure.'
    result=request_attribution(text)
    assert len(result["current_text"])==len(text)
    for span in result["reported_spans"]:
        assert span["text"]==text[span["start"]:span["end"]]
        assert result["current_text"][span["start"]:span["end"]].strip()==""
    assert "I only need the brochure" in result["current_text"]


@pytest.mark.parametrize("kind,reason",[("legal_review","LEGAL_QUESTION"),("commercial_exception","COMPLEX_NEGOTIATION")])
def test_llm_can_identify_an_actual_renewed_request_after_a_reference(kind,reason):
    text='You said "a review may be needed"; please arrange that review for me.'
    result=apply_escalation_policy({"primary_intent":"general_question","intent_confidence":.95,
        "intent_entities":{"protected_request":{"kind":kind,"evidence":"please arrange that review for me"}},
        "proposed_reply":"The request needs review.","proposed_actions":[],"requires_human":False},inbound=text)
    assert result["requires_human"] and result["escalation_decision"]["reason"]==reason
    assert result["escalation_decision"]["reason_source"]=="llm_current_request"
    assert result["escalation_decision"]["protected_request_accepted"]


@pytest.mark.parametrize("evidence",["I need legal advice","not present in the lead message",""])
def test_model_cannot_use_reported_or_invented_evidence_as_a_current_request(evidence):
    result=apply_escalation_policy({"primary_intent":"request_document","intent_confidence":.95,
        "intent_entities":{"protected_request":{"kind":"legal_review","evidence":evidence}},
        "requires_human":False,"proposed_actions":[],"proposed_reply":"Here is the material."},
        inbound='You said "I need legal advice"; just send the approved brochure.')
    assert not result["requires_human"]
    assert not result["escalation_decision"]["protected_request_accepted"]


@pytest.mark.parametrize("confidence,clarify",[(.2,False),(.99,True),(None,False),(True,False)])
def test_untrusted_protected_request_does_not_override_clarification(confidence,clarify):
    result=apply_escalation_policy({"primary_intent":"general_question","intent_confidence":confidence,
        "requires_clarification":clarify,"intent_entities":{"protected_request":{"kind":"legal_review","evidence":"please arrange that review"}},
        "requires_human":False,"proposed_actions":[]},inbound='You said "a review may help"; please arrange that review')
    assert not result["escalation_decision"]["protected_request_accepted"]
    assert not result["requires_human"]


@pytest.mark.parametrize("entity",[[],"legal_review",{"kind":[],"evidence":"ask"},{"kind":"secret","evidence":"ask"},
    {"kind":"legal_review","evidence":""},{"kind":"legal_review","evidence":"x"*501}])
def test_malformed_optional_contract_is_rejected_without_crashing(entity):
    from app.modules.sales_agent.intent_contract import normalize_intent
    result=normalize_intent({"primary_intent":"general_question","intent_confidence":.95,
        "intent_entities":{"protected_request":entity}})
    assert result["requires_clarification"]
    assert "invalid_entity:protected_request" in result["intent_contract_issues"]


def test_graph_applies_typed_current_request_without_replacing_published_prompts(case):
    result,model=model_turn(case,'You said "a legal review may help"; please arrange that review.',primary="general_question",
        entities={"protected_request":{"kind":"legal_review","evidence":"please arrange that review"}},reply="I can refer that for review.")
    assert result["requires_human"] and result["escalation_decision"]["reason"]=="LEGAL_QUESTION"
    messages=model.await_args.args[2]
    assert any("request_attribution" in m["content"] for m in messages)
    assert any("protected_request" in m["content"] for m in messages)


def test_live_renewed_request_has_consistent_case_notification_reply_and_trace(case):
    from app.modules.governance.models import NotificationOutbox
    from app.modules.sales_agent.models import AgentRun
    db,company,project,lead,conversation=case
    result,_=model_turn(case,'You said "a review may help"; please arrange that review.',primary="general_question",
        entities={"protected_request":{"kind":"legal_review","evidence":"please arrange that review"}},reply="I can refer that.")
    dispatch,slots,graph,ids=run_live(case,'You said "a review may help"; please arrange that review.',result)
    assert db.get(SalesConversation,ids[0]).is_paused
    assert db.query(HumanInterventionCase).one().reason=="LEGAL_QUESTION"
    assert db.query(NotificationOutbox).one().payload_json["reason"]=="LEGAL_QUESTION"
    assert "legal review" in dispatch.await_args.kwargs["content"]
    assert db.query(AgentRun).one().output_snapshot["escalation_decision"]["reason_source"]=="llm_current_request"

