"""Groups 1–3: offline contracts and scoped persistence, not LLM accuracy."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from test_sales_turn_1720 import case, outbound
from app.core.config import settings
from app.modules.ai_core.models import AIConfiguration
from app.modules.sales_agent.dialogue_models import SalesDialogueEvent, SalesDialogueState
from app.modules.sales_agent.dialogue_store import Scope, DialogueConflict, load, save
from app.modules.sales_agent.models import SalesConversationLeadContext, SalesMessage, OutboundMessage
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.projects.models import ProjectPropertyType, SalesAssetShare
from app.modules.sales_agent.understanding_contract import DialogueState, ToolResult, parse, response_schema
from app.modules.sales_agent.understanding_evaluation import evaluate
from app.modules.sales_agent.understanding_service import preview

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/sales_understanding_cases.json'
CASES = json.loads(FIXTURE.read_text())['cases']


def scope_of(case):
    _, company, project, lead, conversation = case
    return Scope(company.id, project.id, conversation.id, lead.id)


@pytest.mark.parametrize('scenario', CASES, ids=lambda c: c['id'])
def test_scripted_understanding_scenarios(scenario):
    assert evaluate(scenario)['passed']


@pytest.mark.parametrize('change', [
    {'confidence': True}, {'confidence': '0.99'}, {'confidence': float('nan')},
    {'confidence': -1}, {'confidence': 1.01}, {'confidence': float('inf')},
    {'requires_clarification': 'false'}, {'version': 'sales-understanding/99'},
    {'reply': 'invented reply'}, {'actions': ['book']},
    {'all_of': []}, {'all_of': ['a', 'a', 'b']}, {'all_of': ['foreign']},
    {'requires_clarification': True, 'clarification_question': None},
    {'clarification_question': 'Unrequested question?'},
])
def test_malformed_model_contract_is_rejected(change):
    payload = deepcopy(CASES[0]['model_output']); payload.update(change)
    with pytest.raises(ValueError):
        parse(json.dumps(payload), CASES[0]['inbound'])


@pytest.mark.parametrize('evidence', ['last turn', ' ',  'x'*2001])
def test_evidence_must_be_verbatim_in_current_message(evidence):
    payload = deepcopy(CASES[0]['model_output']); payload['requests'][0]['evidence'] = evidence
    with pytest.raises(ValueError):
        parse(json.dumps(payload), CASES[0]['inbound'])


@pytest.mark.parametrize('raw', ['{}', '[]', 'null', 'not JSON', '{"version":1,"version":2}', 'x'*64001, '['*2000+']'*2000, None])
def test_parser_rejects_bad_or_oversized_json(raw):
    with pytest.raises(ValueError):
        parse(raw, 'message')


def test_relationships_exclusions_and_unknown_subjects_are_not_silently_dropped():
    original = deepcopy(CASES[0]['model_output'])
    for mutate in ('duplicate_id', 'exclude_in_all', 'unknown_topic', 'unknown_subject', 'wrong_subject', 'extra_nested', 'repeated_alternative'):
        payload = deepcopy(original)
        if mutate == 'duplicate_id': payload['requests'][1]['id'] = 'a'
        if mutate == 'exclude_in_all': payload['requests'][0]['polarity'] = 'exclude'
        if mutate == 'unknown_topic': payload['requests'][0]['topic'] = 'visit_picture'
        if mutate == 'unknown_subject': payload['requests'][0]['subject'] = 'secret'
        if mutate == 'wrong_subject': payload['requests'][1]['subject'] = 'brochure'
        if mutate == 'extra_nested': payload['requests'][0]['url'] = 'https://example.com'
        if mutate == 'repeated_alternative':
            payload['all_of'] = []
            payload['alternatives'] = [{'id':'or', 'request_ids':['a','a'], 'evidence':'brochure'}]
        with pytest.raises(ValueError): parse(json.dumps(payload), CASES[0]['inbound'])


def test_strict_schema_requires_all_object_fields_and_forbids_extras():
    def check(node):
        if isinstance(node, dict):
            assert 'default' not in node
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values(): check(child)
        if isinstance(node, list):
            for child in node: check(child)
    check(response_schema())


def test_state_validates_task_graph_versions_and_expiration():
    good = {'tasks':[{'id':'a','topic':'materials','status':'pending'},
                     {'id':'b','topic':'financing','status':'suspended','depends_on':['a']}]}
    assert len(DialogueState.model_validate(good).tasks) == 2
    for bad in ({'version':'unknown'}, {'tasks':[good['tasks'][0],good['tasks'][0]]},
                {'tasks':[{'id':'a','topic':'human','status':'pending','depends_on':['b']}]},
                {'tasks':[{'id':'a','topic':'human','status':'pending','depends_on':['a']}]},
                {'offers':[{'kind':'property','message_id':'id','option_ids':[],'expires_at':'tomorrow'}]},
                {'offers':[{'kind':'property','message_id':'id','option_ids':[],'expires_at':'2026-11-06T12:00:00'}]}):
        with pytest.raises(ValueError): DialogueState.model_validate(bad)


@pytest.mark.parametrize('status', ['success','empty','partial','revoked','denied','conflict','error','uncertain'])
def test_tool_result_contract_distinguishes_failure_from_empty(status):
    assert ToolResult(operation_id='offline', status=status).status == status


def test_legacy_read_creates_nothing_and_save_survives_new_session(case):
    db, *_ = case; scope = scope_of(case)
    assert load(db, scope) == (0, DialogueState())
    assert db.query(SalesDialogueState).count() == db.query(SalesDialogueEvent).count() == 0
    state = DialogueState(tasks=[{'id':'read','topic':'materials','status':'pending'}])
    assert save(db, scope, event_key='first', expected_revision=0, state=state)[0] == 1
    db.commit()
    with Session(db.get_bind()) as restarted:
        assert load(restarted, scope) == (1, state)


def test_same_event_retries_once_and_changed_content_or_revision_conflicts(case):
    db, *_ = case; scope = scope_of(case); state = DialogueState()
    save(db, scope, event_key='one', expected_revision=0, state=state); db.commit()
    assert save(db, scope, event_key='one', expected_revision=0, state=state)[0] == 1
    with pytest.raises(DialogueConflict): save(db, scope, event_key='one', expected_revision=1, state=state)
    with pytest.raises(DialogueConflict): save(db, scope, event_key='two', expected_revision=0, state=state)
    with pytest.raises(DialogueConflict):
        save(db, scope, event_key='one', expected_revision=0, state=DialogueState(tasks=[{'id':'x','topic':'human','status':'blocked'}]))
    assert db.query(SalesDialogueEvent).count() == 1


def test_two_sessions_with_same_revision_cannot_overwrite(case):
    db, *_ = case; scope = scope_of(case)
    save(db, scope, event_key='initial', expected_revision=0, state=DialogueState()); db.commit()
    with Session(db.get_bind()) as other:
        assert load(other, scope)[0] == 1
        save(db, scope, event_key='winner', expected_revision=1, state=DialogueState()); db.commit()
        with pytest.raises(DialogueConflict):
            save(other, scope, event_key='stale', expected_revision=1, state=DialogueState())
        other.rollback()
    assert load(db, scope)[0] == 2
    assert db.query(SalesDialogueEvent).count() == 2


def test_caller_rollback_reverts_both_new_state_and_event(case):
    db, *_ = case; scope = scope_of(case)
    save(db, scope, event_key='rollback', expected_revision=0, state=DialogueState())
    db.rollback()
    assert db.query(SalesDialogueState).count() == db.query(SalesDialogueEvent).count() == 0
    assert load(db, scope)[0] == 0


def test_unknown_stored_version_is_not_silently_downgraded(case):
    db, *_ = case; scope = scope_of(case)
    save(db, scope, event_key='initial', expected_revision=0, state=DialogueState()); db.commit()
    row = db.query(SalesDialogueState).one(); row.schema_version = 'sales-dialogue/99'; db.commit()
    with pytest.raises(ValueError, match='schema version'): load(db, scope)
    with pytest.raises(ValueError, match='schema version'):
        save(db, scope, event_key='downgrade', expected_revision=1, state=DialogueState())


@pytest.mark.parametrize('field', ['company_id','project_id','conversation_id','lead_id'])
def test_foreign_scope_cannot_read_or_write(case, field):
    db, *_ = case; scope = replace(scope_of(case), **{field:'foreign'})
    with pytest.raises(PermissionError): load(db, scope)
    with pytest.raises(PermissionError): save(db, scope, event_key='bad', expected_revision=0, state=DialogueState())
    assert db.query(SalesDialogueEvent).count() == 0


def test_inactive_opportunity_and_stale_offers_are_rejected(case):
    db, company, project, lead, conversation = case; scope = scope_of(case)
    old = outbound(db, conversation, '1. Old property', seconds=-100)
    db.add(SalesConversationLeadContext(conversation_id=conversation.id, lead_id=lead.id, is_active=True,
                                        activated_at=datetime.utcnow()-timedelta(seconds=50))); db.commit()
    with pytest.raises(PermissionError):
        save(db, scope, event_key='old', expected_revision=0, state=DialogueState(offers=[{'kind':'property','message_id':old.id,'option_ids':[]}]))
    db.query(SalesConversationLeadContext).first().is_active = False; db.commit()
    with pytest.raises(PermissionError): load(db, scope)


def test_property_and_offer_ids_are_scoped_and_events_preserve_snapshots(case):
    db, company, project, lead, conversation = case; scope = scope_of(case)
    property_type = ProjectPropertyType(project_id=project.id, name='Generic studio', review_status='confirmed')
    db.add(property_type); db.commit()
    message = outbound(db, conversation, '1. Generic studio', {'lead_id':lead.id})
    state = DialogueState(selected_property_type_id=property_type.id,
        offers=[{'kind':'property','message_id':message.id,'option_ids':[property_type.id]}])
    save(db, scope, event_key='selection', expected_revision=0, state=state); db.commit()
    for bad in (state.model_copy(update={'selected_property_type_id':'foreign'}),
                DialogueState(offers=[{'kind':'property','message_id':message.id,'option_ids':['foreign']}]),
                DialogueState(offers=[{'kind':'material','message_id':message.id,'option_ids':['foreign']}])):
        with pytest.raises(PermissionError): save(db, scope, event_key='bad', expected_revision=1, state=bad)
    save(db, scope, event_key='second', expected_revision=1, state=DialogueState()); db.commit()
    original = db.query(SalesDialogueEvent).filter_by(event_key='selection').one()
    assert original.state_after['selected_property_type_id'] == property_type.id
    original.kind = 'altered'
    with pytest.raises(ValueError, match='append-only'): db.flush()
    db.rollback()
    db.delete(db.query(SalesDialogueEvent).first())
    with pytest.raises(ValueError, match='append-only'): db.flush()
    db.rollback()


@pytest.mark.parametrize('revision', [-1, True, '0'])
def test_invalid_expected_revision_rejected(case, revision):
    db, *_ = case
    with pytest.raises(ValueError): save(db, scope_of(case), event_key='x', expected_revision=revision, state=DialogueState())


def prepare_preview(case, monkeypatch, scenario=None):
    db, company, project, lead, conversation = case
    monkeypatch.setattr(settings, 'SALES_UNDERSTANDING_PREVIEW_ENABLED', True)
    scenario = scenario or CASES[0]
    config = AIConfiguration(company_id=None, agent_ventas={'model':'test/offline', 'system_prompt':'Published sales guidance'})
    db.add(config)
    inbound = SalesMessage(conversation_id=conversation.id, channel='sms', direction='inbound', role='user',
        content=scenario['inbound'], metadata_json={'lead_id':lead.id})
    db.add(inbound); db.commit()
    return inbound, AsyncMock(return_value=json.dumps(scenario['model_output']))


def test_preview_disabled_before_any_db_or_provider_use(monkeypatch):
    monkeypatch.setattr(settings, 'SALES_UNDERSTANDING_PREVIEW_ENABLED', False)
    infer = AsyncMock()
    with pytest.raises(PermissionError, match='disabled'):
        asyncio.run(preview(None, Scope('a','b','c','d'), inbound_message_id='x', expected_revision=0, event_key='x', infer=infer))
    infer.assert_not_awaited()


def test_preview_persists_understanding_without_business_effects_or_task_loss(case, monkeypatch):
    db, company, project, lead, conversation = case; scope = scope_of(case)
    inbound, infer = prepare_preview(case, monkeypatch)
    state = DialogueState(tasks=[{'id':'old','topic':'catalog','status':'suspended'}],
        constraints=[{'topic':'appointment','scope':'until_explicit_change','evidence':'No visits yet'}],
        preferences=[{'key':'property','value':'Loft','evidence':'Loft'}])
    save(db, scope, event_key='prior', expected_revision=0, state=state); db.commit()
    args = dict(inbound_message_id=inbound.id, expected_revision=1, event_key='preview', infer=infer)
    result = asyncio.run(preview(db, scope, **args)); db.commit()
    assert result.status == 'accepted' and result.revision == 2
    assert result.state.tasks == state.tasks and result.state.constraints == state.constraints
    assert result.state.preferences == state.preferences
    assert result.state.last_understanding.permits('financing')
    assert asyncio.run(preview(db, scope, **args)) == result
    infer.assert_awaited_once()
    assert db.query(Meeting).count() == db.query(OutboundMessage).count() == db.query(SalesAssetShare).count() == 0
    assert db.query(SalesMessage).count() == 1
    assert not conversation.is_paused
    event = db.query(SalesDialogueEvent).filter_by(event_key='preview').one()
    meta = event.payload_json['metadata']
    from app.modules.sales_agent.understanding_prompt import PROMPT_VERSION
    assert meta['model'] == 'test/offline' and meta['prompt_snapshot']['version'] == 'sales-understanding-prompt/2.9'
    assert 'Published sales guidance' in json.dumps(meta['model_request'])
    assert 'openrouter_api_key' not in json.dumps(meta)
    assert meta['model_request_sha256']
    assert db.query(AIConfiguration).filter_by(company_id=None).one().agent_ventas['model'] == 'test/offline'


@pytest.mark.parametrize('response,status', [('not JSON','invalid_model_contract'),
    (json.dumps({**CASES[0]['model_output'], 'confidence':True}),'invalid_model_contract'),
    (RuntimeError('secret=do-not-persist'), 'provider_error')])
def test_bad_preview_retains_prior_state_and_records_safe_failure(case, monkeypatch, response, status):
    db, *_ = case; inbound, infer = prepare_preview(case, monkeypatch)
    if isinstance(response, Exception): infer.side_effect = response
    else: infer.return_value = response
    result = asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='bad', infer=infer))
    db.commit()
    assert result.status == status and result.state.last_understanding is None
    meta = db.query(SalesDialogueEvent).one().payload_json['metadata']
    assert 'do-not-persist' not in json.dumps(meta)
    assert meta['error_code'] in {'RuntimeError','understanding_validation_failed'}
    assert db.query(Meeting).count() == 0


def test_preview_rejects_foreign_or_outbound_message_and_stale_revision_before_model(case, monkeypatch):
    db, _, _, _, conversation = case; inbound, infer = prepare_preview(case, monkeypatch)
    other = outbound(db, conversation, 'Not inbound')
    for message_id in ('missing', other.id):
        with pytest.raises(PermissionError): asyncio.run(preview(db, scope_of(case), inbound_message_id=message_id, expected_revision=0, event_key='x', infer=infer))
    with pytest.raises(DialogueConflict): asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=5, event_key='x', infer=infer))
    infer.assert_not_awaited()


def test_preview_diagnostics_redact_credentials_in_input(case, monkeypatch):
    db, *_ = case; inbound, infer = prepare_preview(case, monkeypatch)
    inbound.content += ' password=private-value'; db.commit()
    asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='redact', infer=infer)); db.commit()
    meta = db.query(SalesDialogueEvent).one().payload_json['metadata']
    assert 'private-value' not in json.dumps(meta)
    assert '[REDACTED]' in json.dumps(meta)


def test_preview_uses_native_schema_adapter_without_committing_or_changing_config(case, monkeypatch):
    db, company, *_ = case; inbound, _ = prepare_preview(case, monkeypatch)
    config = db.query(AIConfiguration).filter_by(company_id=None).one()
    config.openrouter_api_key = 'test-credential'
    db.commit()
    original = deepcopy(config.agent_ventas)
    company.name = 'Caller pending value'
    with patch('app.integrations.openrouter_client.generate_llm_response', new=AsyncMock(return_value=json.dumps(CASES[0]['model_output']))) as adapter, patch.object(db, 'commit', wraps=db.commit) as commit:
        result = asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='adapter'))
        commit.assert_not_called()
    assert result.status == 'accepted' and config.agent_ventas == original
    args, kwargs = adapter.await_args
    assert args[0] == 'test-credential' and args[1] == 'test/offline'
    assert kwargs['response_format']['json_schema']['strict'] is True
    assert kwargs['usage_context'].company_id == company.id
    request = db.query(SalesDialogueEvent).one().payload_json['metadata']['model_request']
    assert request == {'model':args[1], 'messages':args[2], 'temperature':kwargs['temperature'], 'response_format':kwargs['response_format']}
    db.rollback()
    assert db.query(SalesDialogueEvent).count() == 0
    assert company.name != 'Caller pending value'


def test_preview_history_excludes_future_and_wrong_opportunity_messages(case, monkeypatch):
    db, _, _, lead, conversation = case; inbound, infer = prepare_preview(case, monkeypatch)
    past = inbound.created_at - timedelta(seconds=1)
    future = inbound.created_at + timedelta(seconds=1)
    db.add_all([
        SalesMessage(conversation_id=conversation.id, channel='sms', direction='outbound', role='assistant', content='Allowed previous answer', created_at=past),
        SalesMessage(conversation_id=conversation.id, channel='sms', direction='outbound', role='assistant', content='WRONG OPPORTUNITY', metadata_json={'lead_id':'foreign'}, created_at=past),
        SalesMessage(conversation_id=conversation.id, channel='sms', direction='outbound', role='assistant', content='FUTURE ANSWER', created_at=future),
    ]); db.commit()
    asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='history', infer=infer))
    body = json.loads(infer.await_args.args[1][1]['content'])
    assert [{k:r[k] for k in ('role','content')} for r in body['history']] == [{'role':'assistant','content':'Allowed previous answer'}]


def test_preview_limits_context_before_inference_and_rejects_deleted_lead(case, monkeypatch):
    db, _, _, lead, _ = case; inbound, infer = prepare_preview(case, monkeypatch)
    inbound.content = 'x'*64000; db.commit()
    with pytest.raises(ValueError, match='limit'):
        asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='limit', infer=infer))
    lead.deleted_at = datetime.utcnow(); db.commit()
    with pytest.raises(PermissionError): load(db, scope_of(case))
    infer.assert_not_awaited()


def test_preview_key_cannot_be_reused_for_another_inbound(case, monkeypatch):
    db, _, _, lead, conversation = case; inbound, infer = prepare_preview(case, monkeypatch)
    asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='same', infer=infer)); db.commit()
    second = SalesMessage(conversation_id=conversation.id, channel='sms', direction='inbound', role='user', content='Different request')
    db.add(second); db.commit()
    with pytest.raises(DialogueConflict):
        asyncio.run(preview(db, scope_of(case), inbound_message_id=second.id, expected_revision=0, event_key='same', infer=infer))
    infer.assert_awaited_once()


def test_preview_invalid_parameters_fail_before_inference(case, monkeypatch):
    db, *_ = case; inbound, infer = prepare_preview(case, monkeypatch)
    for key, revision in (('',0), ('x'*121,0), ('key',True), ('key',-1)):
        with pytest.raises(ValueError):
            asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=revision, event_key=key, infer=infer))
    infer.assert_not_awaited()


def test_oversized_invalid_response_is_audited_with_bounded_redacted_excerpt(case, monkeypatch):
    db, *_ = case; inbound, infer = prepare_preview(case, monkeypatch)
    infer.return_value = 'password=do-not-save ' + 'ñ'*100000
    result = asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='oversize', infer=infer))
    db.commit()
    assert result.status == 'invalid_model_contract'
    meta = db.query(SalesDialogueEvent).one().payload_json['metadata']
    assert meta['raw_response_truncated'] and len(meta['raw_response'].encode()) < 16010
    assert meta['raw_response_sha256'] and 'do-not-save' not in meta['raw_response']


def test_invalid_new_interpretation_keeps_previous_valid_understanding(case, monkeypatch):
    db, _, _, lead, conversation = case; inbound, infer = prepare_preview(case, monkeypatch)
    good = asyncio.run(preview(db, scope_of(case), inbound_message_id=inbound.id, expected_revision=0, event_key='good', infer=infer)); db.commit()
    second = SalesMessage(conversation_id=conversation.id, channel='sms', direction='inbound', role='user', content='Maybe something else')
    db.add(second); db.commit(); infer.return_value = 'invalid JSON'
    bad = asyncio.run(preview(db, scope_of(case), inbound_message_id=second.id, expected_revision=1, event_key='bad-next', infer=infer)); db.commit()
    assert bad.status == 'invalid_model_contract' and bad.revision == 2
    assert bad.state.last_understanding == good.state.last_understanding


def test_offline_harness_has_no_provider_or_database_dependency(tmp_path):
    report = tmp_path / 'offline.json'
    result = subprocess.run([sys.executable, '-m', 'app.modules.sales_agent.understanding_evaluation',
        '--cases', str(FIXTURE), '--output', str(report)], cwd=ROOT, capture_output=True, text=True,
        env={'PATH':'/usr/bin:/bin'}, timeout=30)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    assert data['passed'] == data['total'] == len(CASES)
    assert data['external_actions'] == 0 and data['model_quality_evaluated'] is False


def test_migration_upgrade_rollback_and_reupgrade_on_isolated_schema(case):
    db, *_ = case; engine = db.get_bind(); db.close()
    from app.db.postgres import Base
    spec = importlib.util.spec_from_file_location('dialogue_migration', ROOT/'alembic/versions/20261106_sales_dialogue.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.down_revision == '20261104_inventory_confirmation'
    for name in ('sales_dialogue_events', 'sales_dialogue_states'):
        Base.metadata.tables[name].drop(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            for name in ('sales_dialogue_states', 'sales_dialogue_events'):
                columns = {c['name'] for c in inspect(connection).get_columns(name)}
                assert columns == set(Base.metadata.tables[name].columns.keys())
                assert connection.exec_driver_sql(f'SELECT count(*) FROM {name}').scalar() == 0
            migration.downgrade()
            assert 'sales_dialogue_states' not in inspect(connection).get_table_names()
            migration.upgrade()
    assert db.query(Lead).count() == 1  # Existing business data is not backfilled or changed.


def test_live_modules_do_not_import_or_invoke_the_preview_engine():
    for name in ('graph.py','live_service.py','live_worker.py','service.py','router.py'):
        text = (ROOT/'app/modules/sales_agent'/name).read_text()
        assert 'understanding_service' not in text and 'dialogue_store' not in text
