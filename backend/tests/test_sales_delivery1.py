"""Delivery 1: current routing, evidence anchoring and isolated shared simulation."""
import asyncio
import json
from dataclasses import replace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_active_integration import understanding
from app.core.config import settings
from app.modules.sales_agent.active_service import selected_policy, ENGINE
from app.modules.sales_agent.next_flow import selected
from app.modules.sales_agent.runtime_policy import RuntimePolicy
from app.modules.sales_agent.understanding_contract import parse
from app.modules.sales_agent.evidence import EvidenceError
from app.modules.sales_agent.language_policy import detect
from app.modules.sales_agent.models import AgentRun, OutboundMessage
from app.modules.projects.models import ProjectPropertyType


@pytest.mark.parametrize('old_mode', ['disabled', 'shadow', 'active'])
def test_current_workflow_ignores_old_flags_lists_and_modes(agent, monkeypatch, old_mode):
    monkeypatch.setattr(settings, 'SALES_DIALOGUE_RUNTIME_ENABLED', False)
    monkeypatch.setattr(settings, 'SALES_NEXT_FLOW_ENABLED', False)
    monkeypatch.setattr(settings, 'SALES_NEXT_FLOW_PROJECT_IDS', 'invalid,')
    agent.config.agent_ventas = {**agent.config.agent_ventas, 'runtime_config': {
        'mode': old_mode, 'scope': 'cohort', 'company_ids': ['old'], 'project_ids': []}}
    agent.db.add(ProjectPropertyType(project=agent.project, name='Current approved home', review_status='confirmed'))
    agent.db.commit()
    assert selected(agent.scope)
    assert selected_policy(agent.db, replace(agent.scope, company_id='new-company')).mode == 'active'
    text = 'Show me property types'
    _, run = agent.turn(text, understanding(text, 'catalog'))
    assert run.status == 'completed' and run.graph_version == ENGINE
    assert run.prompt_snapshot['version'] == 'sales-understanding-prompt/2.8'
    assert 'Current approved home' in agent.reply()
    agent.legacy.assert_not_called()


@pytest.mark.parametrize('quote', ['show me property types', 'Show  me property types', 'Show\nme property types'])
def test_format_only_quotes_anchor_to_original_message(quote):
    text='Show me property types'
    value=understanding(text,'catalog').model_dump()
    value['requests'][0]['evidence']=quote
    assert parse(json.dumps(value),text).requests[0].evidence==text


@pytest.mark.parametrize('quote', ['I want to see property types', 'Show me apartment types', 'From a previous message'])
def test_semantic_or_historical_substitutions_remain_invalid(quote):
    text='Show me property types';value=understanding(text,'catalog').model_dump()
    value['requests'][0]['evidence']=quote
    with pytest.raises(EvidenceError) as error:parse(json.dumps(value),text)
    assert error.value.issues[0]['location']==['requests',0,'evidence']
    assert quote not in str(error.value.issues)


def test_ambiguous_format_recovery_is_rejected():
    value=understanding('Photos PHOTOS','materials',subjects={0:'photos'}).model_dump()
    value['requests'][0]['evidence']='photos'
    with pytest.raises(EvidenceError):parse(json.dumps(value),'Photos PHOTOS')


def test_field_specific_repair_preserves_original_intent(agent):
    text='Show me property types'
    bad=understanding(text,'catalog').model_dump();bad['requests'][0]['evidence']='I want property types'
    agent.infer.side_effect=[json.dumps(bad),understanding(text,'catalog').model_dump_json()]
    _,run=agent.turn(text,json.dumps(bad))
    feedback=json.loads(agent.infer.call_args.args[1][-1]['content'])
    assert feedback['validation_issues'][0]['location']==['requests',0,'evidence']
    assert feedback['current_message']==text
    assert run.error_code is None


@pytest.mark.parametrize('text',[
    'I feel bad','I feel awful','I am sad','I feel stressed','Show me photographs','Show me property types',
    'I would like to he information about propertied','About available properties',
    'What properties do you have available','Show me the appartment picturs',
])
def test_conversational_and_imperfect_english_reaches_understanding(text):
    assert not detect(text).needs_reentry


def test_mixed_non_english_clause_stays_gated():
    assert detect('Give me details, quiero fotos también').needs_reentry


def test_simulator_uses_current_coordinator_without_provider_calls(agent):
    from app.modules.sales_agent.service import simulate_turn
    from app.modules.sales_agent.execution import simulation
    agent.conversation.channel='simulation';agent.lead.is_demo=True
    agent.project.is_demo=True;agent.lead.consent_status='granted_simulation'
    agent.db.add(ProjectPropertyType(project=agent.project,name='Simulated home',review_status='confirmed'))
    agent.db.commit();text='Show me property types'
    agent.infer.return_value=understanding(text,'catalog').model_dump_json()
    with agent.patched():
        result=asyncio.run(simulate_turn(agent.db,company_id=agent.company.id,lead_id=agent.lead.id,
            inbound_text=text,event_id='delivery1-simulation'))
    assert result['mode']=='simulation' and 'Simulated home' in result['reply']
    assert agent.db.query(AgentRun).filter_by(id=result['run_id']).one().graph_version==ENGINE
    assert agent.db.query(OutboundMessage).count()==0
    assert simulation() is None
    agent.send.assert_not_awaited();agent.legacy.assert_not_called()


def test_simulation_adapter_cannot_resume_human_pause(agent):
    from app.modules.sales_agent.service import simulate_turn
    agent.conversation.channel='simulation';agent.lead.is_demo=True
    agent.conversation.is_paused=True;agent.conversation.pause_reason='Paused by user'
    agent.db.commit()
    with pytest.raises(HTTPException):
        asyncio.run(simulate_turn(agent.db,company_id=agent.company.id,lead_id=agent.lead.id,inbound_text='Hello'))
    agent.send.assert_not_awaited()


def test_demo_is_never_contacted_through_live_channel(agent):
    agent.lead.is_demo=True;agent.db.commit()
    with agent.patched():
        from app.modules.sales_agent import live_service as live
        from app.modules.sales_agent.models import SalesMessage
        row=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='Hello',status='received')
        agent.db.add(row);agent.db.commit()
        asyncio.run(live.process_live_inbound(agent.conversation.id,row.id))
    agent.send.assert_not_awaited();agent.legacy.assert_not_called()


def test_runtime_limits_stay_validated():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):RuntimePolicy.model_validate({'max_steps':1000})


@pytest.mark.parametrize('notes',[
    'Use standard Company compliance; no Project-specific notes',
    ['Use standard Company compliance; no Project-specific notes'],
    ['Use standard Company compliance','no Project-specific notes'],
    'Not applicable',
])
def test_platform_onboarding_standard_choices_do_not_hold_the_catalog(agent, notes):
    from app.modules.sales_agent.action_policy import resolve
    assert not resolve(agent.db,agent.scope,{}, {'compliance_notes':notes})['held_topics']


def test_free_text_is_not_misread_as_permission_to_waive_restrictions(agent):
    from app.modules.sales_agent.action_policy import resolve
    policy=resolve(agent.db,agent.scope,{}, {'compliance_notes':'Use standard Company compliance, but get human approval before sharing prices'})
    assert policy['held_topics'] and policy['unresolved']


def test_repeated_failure_is_reported_once_and_does_not_loop_replies(agent):
    from app.modules.governance.models import NotificationOutbox
    text='Show me property types'
    bad=understanding(text,'catalog').model_dump()
    bad['requests'][0]['evidence']='A paraphrase that is not the current message'
    for _ in range(4):agent.turn(text,json.dumps(bad))
    assert agent.send.await_count==2
    assert agent.db.query(NotificationOutbox).filter_by(event_type='sales_processing_issue').count()==1
    assert not agent.conversation.is_paused
    agent.turn(text,understanding(text,'catalog'))
    assert agent.send.await_count==3


def test_stop_works_before_any_model_has_been_configured(agent):
    from app.modules.ai_core.models import AIConfiguration
    agent.db.query(AIConfiguration).delete();agent.db.commit()
    _,run=agent.turn('STOP',understanding('STOP','opt_out'))
    assert agent.lead.is_opt_out and run.status=='completed'
    agent.infer.assert_not_awaited();agent.legacy.assert_not_called()


def test_historical_unfinished_effect_is_not_reinterpreted(agent):
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent import live_service as live
    row=SalesMessage(conversation_id=agent.conversation.id,channel='sms',direction='inbound',role='user',content='Yes',status='received')
    agent.db.add(row);agent.db.flush()
    old=AgentRun(conversation_id=agent.conversation.id,event_id='telnyx:'+row.id,mode='live',status='prepared',
        graph_version='historical-engine',toolset_version='old',model='test/offline',prompt_snapshot={},
        input_snapshot={'message_id':row.id},output_snapshot={'existing_effect_receipt':'keep-this'})
    agent.db.add(old);agent.db.commit()
    with agent.patched():asyncio.run(live.process_live_inbound(agent.conversation.id,row.id))
    assert old.status=='blocked' and old.error_code=='historical_turn_requires_reconciliation'
    assert old.output_snapshot=={'existing_effect_receipt':'keep-this'}
    agent.infer.assert_not_awaited();agent.send.assert_not_awaited()


def test_simulated_booking_has_no_external_calendar_or_real_outbound(agent):
    from datetime import datetime
    from app.modules.sales_agent.execution import sandbox
    from test_sales_ai_group_f import book
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    agent.conversation.channel='simulation';agent.lead.is_demo=True
    agent.lead.consent_status='granted_simulation';agent.db.commit()
    with sandbox(agent.db,agent.conversation,datetime.utcnow()), patch('app.integrations.gcalendar_client.create_calendar_event_for_connection') as calendar:
        _,run,meeting,_=book(agent)
    assert meeting.is_demo and run.mode=='simulation'
    assert agent.db.query(SalesBookingOperation).one().calendar_status=='simulation'
    calendar.assert_not_called();agent.send.assert_not_awaited()
    assert agent.db.query(OutboundMessage).count()==0


def test_current_simulation_initial_contact_and_virtual_followup_are_idempotent():
    from datetime import timedelta
    from test_sales_agent_simulation_flow import _db, _fixture, _create
    from app.modules.sales_agent.simulation_service import generate_initial_message,advance_simulation
    from app.modules.sales_agent.models import SalesMessage
    db=_db();company,_,admin,_,_,project,campaign,product=_fixture(db)
    created=_create(db,company,admin,project,campaign,product)
    with patch('app.modules.sales_agent.graph.generate_llm_response',side_effect=AssertionError('legacy graph invoked')):
        first=asyncio.run(generate_initial_message(db,company_id=company.id,simulation_id=created['simulation_id']))
        second=asyncio.run(generate_initial_message(db,company_id=company.id,simulation_id=created['simulation_id']))
        assert first['run_id']==second['run_id'] and first['reply'].startswith('Hi')
        asyncio.run(advance_simulation(db,company_id=company.id,simulation_id=created['simulation_id'],hours=25))
    assert db.query(SalesMessage).filter_by(direction='outbound').count()==2
    assert db.query(OutboundMessage).count()==0


def test_recovery_preserves_a_committed_effect_even_if_a_later_step_fails(agent):
    from test_sales_ai_group_f import book
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.sales_agent.effect_recovery import attempt
    book(agent);op=agent.db.query(SalesBookingOperation).one()
    def committed_then_failed():
        op.calendar_status='synced';agent.db.commit()
        raise ValueError('later local step failed')
    attempt(agent.db,SalesBookingOperation,op.id,committed_then_failed)
    assert op.calendar_status=='synced'


def test_a_foreign_event_collision_cannot_block_or_overwrite_its_receipt(agent):
    from app.modules.sales_agent.models import SalesConversation,SalesMessage
    from app.modules.sales_agent import live_service as live
    from app.modules.sales_agent.dialogue_store import DialogueConflict
    other=SalesConversation(company_id=agent.company.id,project_id=agent.project.id,lead_id=agent.lead.id,
        channel='whatsapp',provider='telnyx',is_paused=False)
    agent.db.add(other);agent.db.flush()
    old=AgentRun(conversation_id=other.id,event_id='telnyx:collision',mode='live',status='prepared',
        graph_version='historical-engine',toolset_version='old',model='test/offline',
        prompt_snapshot={},input_snapshot={},output_snapshot={'receipt':'keep'})
    inbound=SalesMessage(conversation_id=agent.conversation.id,provider_message_id='collision',channel='sms',
        direction='inbound',role='user',content='Yes',status='received')
    agent.db.add_all([old,inbound]);agent.db.commit()
    with agent.patched(),pytest.raises(DialogueConflict):
        asyncio.run(live.process_live_inbound(agent.conversation.id,inbound.id))
    assert old.status=='prepared' and old.output_snapshot=={'receipt':'keep'}
    agent.send.assert_not_awaited()
