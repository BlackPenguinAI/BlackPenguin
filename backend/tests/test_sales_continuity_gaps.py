"""Regressions for verified consent, negated requests and combined pause policy."""
from datetime import datetime

import pytest
from test_sales_turn_1720 import case, model_turn, run_live, outbound
from app.modules.projects.models import ProjectPropertyType
from app.modules.sales_agent.models import SalesConversation
from app.modules.sales_crm.models import Lead
from app.modules.governance.models import HumanInterventionCase, Notification
from app.modules.governance.services import process_notification_outbox
from app.modules.sales_agent.escalation_policy import apply_escalation_policy, notify_sales
from app.modules.users.models import User, UserRole


def test_mixed_objection_keeps_selected_option_and_answers_both_topics(case):
    db,company,project,lead,conversation=case
    first=ProjectPropertyType(project=project,name="Courtyard Studio",bedrooms=0,starting_price=170000,currency="USD",review_status="confirmed")
    second=ProjectPropertyType(project=project,name="Sky Residence",bedrooms=3,starting_price=450000,currency="USD",review_status="confirmed")
    db.add_all([first,second]);db.flush()
    project.profile.profile_data={"amenities":["Library","Shared garden"]}
    project.profile.field_states={"amenities":{"status":"confirmed","applicable":True}}
    db.commit()
    outbound(db,conversation,"Sky Residence starts at 45 USD.",{"selected_property_type_id":second.id})
    result,_=model_turn(case,"You said the price was 45 USD and you missed the amenities. Please check both.",primary="request_pricing",secondary=["request_amenities"],reply="I apologize for the oversight. Sky Residence is 45 USD.")
    assert "450,000 USD" in result["proposed_reply"]
    assert "Library" in result["proposed_reply"] and "Shared garden" in result["proposed_reply"]
    assert "Courtyard Studio" not in result["proposed_reply"]
    assert result["response_policy_trace"]["correction"]["selected_property_type_id"] == second.id


def test_unchanged_approved_price_does_not_claim_a_project_data_change(case):
    db,company,project,lead,conversation=case
    product=ProjectPropertyType(project=project,name="Garden House",bedrooms=2,starting_price=270000,currency="USD",review_status="confirmed")
    db.add(product);db.commit()
    outbound(db,conversation,"Garden House starts at 270,000 USD.",{"selected_property_type_id":product.id})
    result,_=model_turn(case,"That is wrong. Please check the price.",primary="request_pricing",reply="Sorry for the mistake. The new price is 200,000 USD.")
    assert "270,000 USD" in result["proposed_reply"] and "200,000 USD" not in result["proposed_reply"]
    assert "does not confirm a change" in result["proposed_reply"]
    assert not result["response_policy_trace"]["correction"]["previous_monetary_validation"]["replaced"]


def test_low_confidence_remains_a_clarification_when_material_is_missing():
    result=apply_escalation_policy({"primary_intent":"request_visual_material","intent_confidence":.2,
        "requires_clarification":True,"requires_human":False,"commercial_context":{},
        "proposed_actions":[],"proposed_reply":"Which images do you mean?"},
        inbound="Could I see those pictures?",routing={"pause_on_missing_material":False,"pause_on_low_confidence":True})
    assert result["escalation_decision"]["disposition"] == "notify_sales", result["escalation_decision"]
    assert not result['requires_human']
    assert result["escalation_decision"]["reason"] == "LOW_CONFIDENCE"


@pytest.mark.parametrize("text",[
    "I don't need legal advice; just send the approved brochure.",
    "I'm not asking for a special discount; just send the approved price list.",
])
def test_negated_exception_request_does_not_pause_normal_material_request(case,text):
    db,*_=case
    dispatch,slots,graph,ids=run_live(case,text,{"primary_intent":"request_document","intent_confidence":.99})
    assert not db.get(SalesConversation,ids[0]).is_paused
    assert db.query(HumanInterventionCase).count() == 0
    graph.ainvoke.assert_awaited_once()


def test_low_confidence_opt_out_never_sends_false_unsubscribe_confirmation(case):
    db,*_=case
    text="Maybe stop those offers?"
    result,_=model_turn(case,text,primary="opt_out",confidence=.4,reply="You have been unsubscribed and will not receive further messages.")
    dispatch,slots,graph,ids=run_live(case,text,result)
    reply=dispatch.await_args.kwargs["content"]
    assert db.get(Lead,ids[1]).is_opt_out or "You have been unsubscribed" not in reply, {
        "reply":reply,"opted_out":db.get(Lead,ids[1]).is_opt_out,"disposition":result.get("escalation_decision")}


def test_sales_notice_is_delivered_only_to_authorized_company_sales_staff(case):
    db,company,project,lead,conversation=case
    users=[]
    for role in (UserRole.ADMIN,UserRole.SALES,UserRole.MKT):
        user=User(company_id=company.id,email=f"{role.value}@acceptance.invalid",hashed_password="test-only",role=role,is_active=True)
        db.add(user);users.append(user)
    db.flush();lead.assigned_sales_user_id=users[1].id;db.commit()
    expected={users[0].id,users[1].id}
    notify_sales(db,conversation=conversation,lead=lead,decision={"reason":"MISSING_MATERIAL"},event_id="independent-notice",evidence="Requested images are unavailable.")
    db.commit();process_notification_outbox(db,company_id=company.id)
    notifications=db.query(Notification).all()
    assert {n.recipient_user_id for n in notifications} == expected
    assert all("remains active" in n.body for n in notifications)
    assert not conversation.is_paused


@pytest.mark.parametrize("low_flag",[False,True])
@pytest.mark.parametrize("material_flag",[False,True])
@pytest.mark.parametrize("confidence",[.2,.99])
@pytest.mark.parametrize("has_asset",[False,True])
def test_combined_ordinary_pause_flags_are_advisory_and_leave_config_unchanged(low_flag,material_flag,confidence,has_asset):
    routing={"pause_on_low_confidence":low_flag,"pause_on_missing_material":material_flag}
    original=dict(routing)
    result=apply_escalation_policy({"primary_intent":"request_document","intent_confidence":confidence,
        "requires_clarification":confidence < .8,"requires_human":False,"proposed_actions":[],
        "commercial_context":{"available_assets":[{"asset_id":"approved"}] if has_asset else []}},
        inbound="Send the brochure",routing=routing)
    matched=[]
    if low_flag and confidence < .8:matched.append("LOW_CONFIDENCE")
    if material_flag and not has_asset:matched.append("MISSING_MATERIAL")
    assert not result["requires_human"]
    assert result["escalation_decision"]["matched_pause_rules"] == []
    conditions=[]
    if confidence < .8:conditions.append('LOW_CONFIDENCE')
    if not has_asset:conditions.append('MISSING_MATERIAL')
    assert result['escalation_decision']['applicable_conditions']==conditions
    if conditions:assert result['escalation_decision']['reason']==conditions[0]
    assert routing == original


@pytest.mark.parametrize("text",[
    "No necesito asesoría legal; solo quiero el brochure.",
    "No quiero negociar, solo ver el precio aprobado.",
    "No estoy pidiendo un descuento especial; envía la ficha.",
    "Legal advice is not needed. Send the brochure.",
    "I am not requesting any custom terms; just show the floor plan.",
    "I'm not asking for legal advice or custom terms; just the brochure.",
    "No quiero negociar un descuento especial; solo quiero el brochure.",
])
def test_explicit_negations_do_not_require_legal_or_commercial_handoff(text):
    from app.modules.governance.services import escalation_reason
    assert escalation_reason(text) is None


@pytest.mark.parametrize("text,expected",[
    ("I don't need a brochure; I need legal advice.","LEGAL_QUESTION"),
    ("No necesito fotos, pero quiero negociar un descuento especial.","COMPLEX_NEGOTIATION"),
    ("I'm not asking for a special discount, but I need custom terms.","COMPLEX_NEGOTIATION"),
    ("Not only legal advice, I also need a lawyer.","LEGAL_QUESTION"),
    ("Can you negotiate a special discount?","COMPLEX_NEGOTIATION"),
    ("Necesito asesoría legal sobre una cláusula.","LEGAL_QUESTION"),
    ("I don't need legal advice, negotiate a special discount instead.","COMPLEX_NEGOTIATION"),
    ("I'm not asking for a special discount; legal advice and a lawyer are needed.","LEGAL_QUESTION"),
])
def test_affirmative_protected_request_is_not_hidden_by_unrelated_negation(text,expected):
    from app.modules.governance.services import escalation_reason
    assert escalation_reason(text) == expected


@pytest.mark.parametrize("message",["You have been unsubscribed.","I have unsubscribed you.","You will no longer receive messages."])
def test_only_executed_opt_out_can_propose_unsubscribe_confirmation(message):
    result=apply_escalation_policy({"primary_intent":"general_question","intent_confidence":.99,
        "proposed_reply":message,"proposed_actions":[],"requires_human":False},inbound="Tell me about the Project")
    assert "unsubscribed" not in result["proposed_reply"].lower()
    assert "no longer receive" not in result["proposed_reply"].lower()
    assert result["escalation_decision"]["disposition"] == "continue"


def test_uncertain_opt_out_cancels_followups_without_claiming_consent_was_changed(case):
    from datetime import timedelta
    from app.modules.sales_agent.models import SalesFollowUpJob, AgentRun
    db,company,project,lead,conversation=case
    for i,status in enumerate(("pending","processing")):
        db.add(SalesFollowUpJob(conversation_id=conversation.id,scheduled_at=datetime.utcnow()+timedelta(days=1),reason="test",status=status,idempotency_key=f"ambiguous-consent-{i}"))
    lead.next_action_at=datetime.utcnow()+timedelta(days=1);db.commit()
    dispatch,slots,graph,ids=run_live(case,"Maybe stop these offers?",{
        "primary_intent":"opt_out","intent_confidence":.4,"requires_clarification":True,
        "proposed_reply":"You have been unsubscribed.","proposed_actions":[{"type":"share_asset","asset_id":"fake"}]})
    reply=dispatch.await_args.kwargs["content"]
    lead=db.get(Lead,ids[1])
    assert not lead.is_opt_out and lead.next_action_at is None
    assert not db.get(SalesConversation,ids[0]).is_paused
    assert "stop all messages" in reply and "have been unsubscribed" not in reply
    assert all(j.status == "cancelled" for j in db.query(SalesFollowUpJob).all())
    assert db.query(AgentRun).one().output_snapshot["escalation_decision"]["consent_clarification_required"]
    assert db.query(HumanInterventionCase).count() == 0
    assert dispatch.await_args.kwargs["metadata"]["proposed_actions"] == [{"type":"ask_qualification_question"}]


def test_uncertain_opt_out_stays_active_despite_legacy_pause_flag():
    result=apply_escalation_policy({"primary_intent":"opt_out","intent_confidence":.4,
        "proposed_reply":"You have been unsubscribed.","requires_clarification":True},
        inbound="Maybe stop these offers?",routing={"pause_on_low_confidence":True})
    assert not result["requires_human"] and result["escalation_decision"]["reason"] == "LOW_CONFIDENCE"
    assert result['escalation_decision']['disposition']=='notify_sales'
    assert "unsubscribed" not in result["proposed_reply"]


def test_raw_stop_is_unconditional_even_with_invalid_model_confidence_and_staff_flags():
    result=apply_escalation_policy({"primary_intent":"unclear","intent_confidence":.1,"requires_clarification":True},
        inbound="STOP",routing={"pause_on_low_confidence":True,"pause_on_missing_material":True})
    assert result["escalation_decision"]["disposition"] == "opt_out"
    assert not result["escalation_decision"]["consent_clarification_required"]


def test_high_confidence_but_explicitly_unresolved_opt_out_still_needs_confirmation():
    result=apply_escalation_policy({"primary_intent":"opt_out","intent_confidence":.99,"requires_clarification":True,
        "proposed_reply":"You have been unsubscribed.","proposed_actions":[]},inbound="Not those offers, perhaps")
    assert result["requires_clarification"] and result["escalation_decision"]["disposition"] in {"continue","notify_sales"}
    assert "stop all messages" in result["proposed_reply"]


def test_simulation_keeps_uncertain_consent_out_of_proactive_followups():
    import asyncio,json
    from unittest.mock import AsyncMock,patch
    from test_sales_agent_simulation_flow import _db,_fixture,_start
    from app.modules.sales_agent.service import _legacy_simulate_turn as simulate_turn
    from app.modules.sales_agent.models import SalesFollowUpJob
    db=_db();company,_,admin,_,_,project,campaign,product=_fixture(db)
    initial=_start(db,company,admin,project,campaign,product)
    payload={"reply":"You have been unsubscribed.","primary_intent":"opt_out","intent_confidence":.4,"proposed_actions":[]}
    with patch("app.modules.sales_agent.graph.generate_llm_response",AsyncMock(return_value=json.dumps(payload))):
        reply=asyncio.run(simulate_turn(db,company_id=company.id,lead_id=initial["lead_id"],inbound_text="Maybe stop those offers?"))
    assert "stop all messages" in reply["reply"] and "have been unsubscribed" not in reply["reply"]
    assert not db.get(Lead,initial["lead_id"]).is_opt_out
    assert not db.query(SalesFollowUpJob).filter(SalesFollowUpJob.status.in_(["pending","processing"])).count()


def test_simulation_human_control_does_not_get_reset_or_schedule_new_followups():
    import asyncio,json
    from unittest.mock import AsyncMock,patch
    from test_sales_agent_simulation_flow import _db,_fixture,_start
    from app.modules.sales_agent.service import _legacy_simulate_turn as simulate_turn
    from app.modules.sales_agent.models import SalesFollowUpJob
    db=_db();company,_,admin,_,_,project,campaign,product=_fixture(db)
    initial=_start(db,company,admin,project,campaign,product)
    payload={"reply":"A colleague can help.","primary_intent":"human_requested","intent_confidence":.99,"proposed_actions":[]}
    with patch("app.modules.sales_agent.graph.generate_llm_response",AsyncMock(return_value=json.dumps(payload))):
        reply=asyncio.run(simulate_turn(db,company_id=company.id,lead_id=initial["lead_id"],inbound_text="Please transfer me to a person"))
    assert reply["requires_human"]
    assert db.get(Lead,initial["lead_id"]).agent_status == "human_control"
    assert not db.query(SalesFollowUpJob).filter(SalesFollowUpJob.status.in_(["pending","processing"])).count()


def test_live_uncertain_consent_does_not_invoke_cadence_scheduling(case):
    import asyncio
    from unittest.mock import AsyncMock,patch
    from app.modules.sales_agent.live_service import _legacy_process_live_inbound as process_live_inbound
    from app.modules.sales_agent.models import SalesMessage
    db,company,project,lead,conversation=case
    msg=SalesMessage(conversation_id=conversation.id,channel="sms",direction="inbound",role="user",content="Maybe stop those offers?",status="received")
    db.add(msg);db.commit();conversation_id,message_id=conversation.id,msg.id
    graph=AsyncMock();graph.ainvoke.return_value={"primary_intent":"opt_out","intent_confidence":.4,
        "requires_clarification":True,"proposed_reply":"You have been unsubscribed.","proposed_actions":[],"policy_violations":[]}
    with patch("app.modules.sales_agent.live_service.SessionLocal",return_value=db),patch("app.modules.sales_agent.live_service.build_sales_graph",return_value=graph),patch("app.modules.sales_agent.live_service._dispatch",new=AsyncMock(return_value=SalesMessage())),patch("app.modules.sales_agent.live_service._schedule_next_action") as cadence:
        asyncio.run(process_live_inbound(conversation_id,message_id))
    cadence.assert_not_called()


def test_simulated_numeric_choice_cannot_book_during_consent_clarification():
    import asyncio,json
    from datetime import timedelta
    from unittest.mock import AsyncMock,patch
    from test_sales_agent_simulation_flow import _db,_fixture,_start
    from app.modules.sales_agent.service import _legacy_simulate_turn as simulate_turn
    from app.modules.sales_agent.models import SalesMessage,SalesAgentSimulation
    db=_db();company,_,admin,_,_,project,campaign,product=_fixture(db)
    initial=_start(db,company,admin,project,campaign,product)
    simulation=db.get(SalesAgentSimulation,initial["simulation_id"])
    now=datetime.utcnow();slot=now+timedelta(days=2)
    outbound(db,db.get(SalesConversation,simulation.conversation_id),"1. Verified appointment time",{"appointment_offer":{"slots":[slot.isoformat()]}})
    payload={"reply":"You have been unsubscribed.","primary_intent":"opt_out","intent_confidence":.4,"proposed_actions":[]}
    with patch("app.modules.sales_agent.graph.generate_llm_response",AsyncMock(return_value=json.dumps(payload))),patch("app.modules.sales_agent.service.create_agent_appointment") as book:
        result=asyncio.run(simulate_turn(db,company_id=company.id,lead_id=initial["lead_id"],inbound_text="1",virtual_now=now))
    book.assert_not_called()
    assert "stop all messages" in result["reply"]

