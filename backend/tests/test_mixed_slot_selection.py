"""Independent positive/negative contextual routing probes; no real providers."""
from test_sales_turn_1720 import case, model_turn, offer_slot, run_live, outbound, approved_asset
from app.modules.sales_agent.service import _classified_slot_selection
from app.modules.sales_agent.turn_context import appointment_execution_allowed
from datetime import datetime
from datetime import timedelta
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import asyncio
import pytest


def test_mixed_explicit_slot_selection_survives_the_real_graph(case):
    db,company,project,lead,conversation=case
    slot=offer_slot(db,conversation)
    text="The first appointment and send the brochure please"
    result,_=model_turn(case,text,primary="select_appointment_slot",secondary=["request_document"],confidence=.99,reply="I can confirm that time and share the approved brochure.")
    assert not result["requires_clarification"]
    assert appointment_execution_allowed(result),result["response_policy_trace"]
    assert _classified_slot_selection(db,conversation=conversation,project=project,inbound_text=text,result=result,now=datetime.utcnow())==slot


def test_explicit_new_visit_and_materials_remain_executable(case):
    text="Can I book an in-person visit and get the brochure?"
    result,_=model_turn(case,text,primary="request_appointment",secondary=["request_document"],confidence=.99,reply="I can check times and share approved materials.")
    assert appointment_execution_allowed(result),result["response_policy_trace"]


def test_visual_request_remains_non_scheduling_through_the_real_graph(case):
    result,_=model_turn(case,"Pictures of the unit at 3 PM please",primary="select_appointment_slot",secondary=["request_visual_material"],confidence=.99,reply="I can help with approved images.")
    assert not appointment_execution_allowed(result)


@pytest.mark.parametrize("condition",["no_offer","property_offer","expired","ambiguous_time","low_confidence"])
def test_mixed_selection_does_not_bypass_booking_preconditions(case,condition):
    db,company,project,lead,conversation=case
    slot=datetime.utcnow().replace(hour=15,minute=0,second=0,microsecond=0)+timedelta(days=2)
    text="The first appointment and send the brochure please"
    if condition=="property_offer":
        outbound(db,conversation,"1. Studio",{"property_catalog_offer":{"property_type_ids":["studio"]}})
    elif condition!="no_offer":
        slots=[slot.isoformat()]
        if condition=="expired":slots=[(datetime.utcnow()-timedelta(days=2)).isoformat()]
        if condition=="ambiguous_time":
            slots.append((slot+timedelta(days=1)).isoformat());text="3 PM for the appointment and send the brochure please"
        outbound(db,conversation,"Choose a verified time",{"appointment_offer":{"slots":slots}})
    result,_=model_turn(case,text,primary="select_appointment_slot",secondary=["request_document"],confidence=.1 if condition=="low_confidence" else .99)
    assert not appointment_execution_allowed(result)
    assert result["response_policy_trace"]["verified_slot_selection"] is None


def test_live_mixed_selection_books_once_and_includes_requested_file(case):
    from app.modules.sales_agent.live_service import _legacy_process_live_inbound as process_live_inbound
    from app.modules.sales_agent.models import SalesMessage
    db,company,project,lead,conversation=case
    approved_asset(case,["brochure"])
    slot=offer_slot(db,conversation)
    text="The first appointment and send the brochure please"
    result,_=model_turn(case,text,primary="select_appointment_slot",secondary=["request_document"],confidence=.99)
    ids=(conversation.id,lead.id)
    message=SalesMessage(conversation_id=conversation.id,channel="sms",direction="inbound",role="user",content=text,status="received")
    db.add(message);db.commit();message_id=message.id
    graph=AsyncMock();graph.ainvoke.return_value=result
    meeting=SimpleNamespace(id="verified-meeting",meeting_time=slot)
    user=SimpleNamespace(first_name="Example",last_name="Sales",email="sales@example.com")
    with patch("app.modules.sales_agent.live_service.SessionLocal",return_value=db),patch("app.modules.sales_agent.live_service.build_sales_graph",return_value=graph),patch("app.modules.sales_agent.live_service.create_agent_appointment",return_value=(meeting,user)) as book,patch("app.modules.sales_agent.live_service._dispatch",new=AsyncMock()) as dispatch,patch("app.modules.sales_agent.live_service._schedule_next_action"):
        asyncio.run(process_live_inbound(ids[0],message_id))
        asyncio.run(process_live_inbound(ids[0],message_id))
    book.assert_called_once();dispatch.assert_awaited_once()
    reply=dispatch.await_args.kwargs["content"]
    assert "appointment is confirmed" in reply and "/projects/a/" in reply
    assert reply.index("appointment is confirmed")<reply.index("/projects/a/")


def test_simulation_graph_uses_virtual_time_for_verified_selection(case):
    import json
    from app.modules.sales_agent.graph import build_sales_graph
    db,company,project,lead,conversation=case
    # Configure the same published/model test setup as the other graph probes.
    model_turn(case,"Hi",primary="greeting")
    virtual=datetime(2025,1,1,12,0)
    slot=virtual+timedelta(days=1)
    outbound(db,conversation,"Choose the verified time",{"appointment_offer":{"slots":[slot.isoformat()]}})
    payload={"reply":"I can confirm that time.","primary_intent":"select_appointment_slot","secondary_intents":["request_document"],"intent_confidence":.99,"requires_clarification":False,"intent_entities":{},"proposed_actions":[],"requires_human":False}
    with patch("app.modules.sales_agent.graph.generate_llm_response",new=AsyncMock(return_value=json.dumps(payload))):
        result=asyncio.run(build_sales_graph(db).ainvoke({"event_id":"virtual-mixed","mode":"simulation","evaluation_now":virtual.isoformat(),"conversation_id":conversation.id,"company_id":company.id,"project_id":project.id,"lead_id":lead.id,"channel":"simulation","inbound_text":"The first appointment and send the brochure please","requires_human":False,"policy_violations":[]}))
    assert appointment_execution_allowed(result)
    assert result["response_policy_trace"]["verified_slot_selection"]==slot.isoformat()
