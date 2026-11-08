"""Offline regression for the observed production rejection; no real sends/LLM."""
import json
import pytest
from test_sales_active_integration import agent, understanding
from test_sales_turn_1720 import case
from app.modules.sales_agent.models import AgentRun, OutboundMessage
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
from app.modules.sales_agent.understanding_contract import parse
from app.modules.sales_agent.understanding_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from app.modules.projects.models import ProjectPropertyType, SalesAssetShare
from app.modules.sales_crm.models import Meeting

TEXT = 'Give me information about the properties you have available'
BAD = json.dumps(dict(version='sales-understanding/1.0', requests=[
    dict(id='1', topic='inventory', subject='unit_sheet', polarity='request', evidence=TEXT),
    dict(id='2', topic='inventory', subject='unit_sheet', polarity='exclude', evidence=TEXT)],
    all_of=[], alternatives=[], constraints=[], references=[], preferences=[], releases=[],
    requires_clarification=True, clarification_question='What information?', confidence=0))


def test_observed_response_remains_rejected_and_prompt_teaches_valid_example():
    with pytest.raises(ValueError): parse(BAD, TEXT)
    example = SYSTEM_PROMPT.split('Output: ', 1)[1].split('\n', 1)[0]
    result = parse(example, TEXT)
    assert result.permits('inventory') and result.requests[0].subject is None
    assert PROMPT_VERSION == 'sales-understanding-prompt/1.3'


def test_repair_recovers_available_properties_and_retry_does_not_resend(agent):
    agent.db.add(ProjectPropertyType(project=agent.project, name='Approved home', review_status='confirmed', available_units=1))
    agent.db.commit()
    agent.infer.side_effect = [BAD, understanding(TEXT, 'inventory').model_dump_json()]
    message, run = agent.turn(TEXT, BAD)
    assert agent.infer.await_count == 2
    event = agent.db.query(SalesDialogueEvent).filter_by(event_key='active-understanding:'+message.id).one()
    trace = event.payload_json['metadata']
    assert trace['outcome'] == 'accepted'
    assert [a['outcome'] for a in trace['interpretation_attempts']] == ['invalid_model_contract', 'accepted']
    assert trace['interpretation_attempts'][0]['validation_issues']
    assert 'Approved home' in agent.reply()
    assert 'processing your message' not in agent.reply()
    agent.retry(message)
    assert agent.infer.await_count == 2
    assert agent.db.query(AgentRun).count() == agent.db.query(OutboundMessage).count() == 1
    assert agent.db.query(Meeting).count() == agent.db.query(SalesAssetShare).count() == 0
    agent.legacy.assert_not_called()


def test_repeated_invalid_reply_is_bounded_audited_and_does_not_blame_lead(agent):
    message, run = agent.turn(TEXT, BAD)
    assert agent.infer.await_count == 2
    assert 'trouble processing your message' in agent.reply()
    assert 'safely' not in agent.reply()
    assert run.model == 'test/offline' and run.error_code == 'understanding_validation_failed'
    assert run.output_snapshot['interpretation_attempt_count'] == 2
    assert not agent.conversation.is_paused
    assert agent.db.query(Meeting).count() == agent.db.query(SalesAssetShare).count() == 0
    agent.legacy.assert_not_called()


def test_provider_failure_is_not_retried_or_mislabeled_as_contract_failure(agent):
    agent.infer.side_effect = RuntimeError('provider offline')
    _, run = agent.turn(TEXT, BAD)
    assert agent.infer.await_count == 1
    assert run.error_code == 'RuntimeError'
    assert run.output_snapshot['interpretation_outcome'] == 'provider_error'


def test_same_evidence_cannot_simultaneously_request_and_exclude(agent):
    payload = understanding(TEXT, 'inventory').model_dump(mode='json')
    payload['requests'].append({**payload['requests'][0], 'id':'exclude', 'polarity':'exclude'})
    with pytest.raises(ValueError, match='same evidence'):
        parse(json.dumps(payload), TEXT)


def test_manual_takeover_during_repair_prevents_delivery(agent):
    async def repair(*args):
        if agent.infer.await_count == 1: return BAD
        agent.conversation.is_paused = True
        agent.conversation.pause_reason = 'Manual control'
        agent.db.commit()
        return understanding(TEXT, 'inventory').model_dump_json()
    agent.infer.side_effect = repair
    agent.turn(TEXT, BAD)
    assert agent.infer.await_count == 2
    agent.send.assert_not_awaited()
    assert agent.db.query(Meeting).count() == agent.db.query(SalesAssetShare).count() == 0


def test_repair_cannot_use_evidence_from_feedback_or_another_turn(agent):
    corrected = understanding(TEXT, 'inventory').model_dump(mode='json')
    corrected['requests'][0]['evidence'] = 'a different message'
    agent.infer.side_effect = [BAD, json.dumps(corrected)]
    _, run = agent.turn(TEXT, BAD)
    assert agent.infer.await_count == 2
    assert run.output_snapshot['interpretation_outcome'] == 'invalid_model_contract'
    assert agent.db.query(Meeting).count() == agent.db.query(SalesAssetShare).count() == 0
