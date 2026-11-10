"""Contract and actual recovery regressions; live model quality is tested by variants CLI."""
import json
from types import SimpleNamespace as NS
import pytest
from test_sales_active_integration import understanding
from test_sales_ai_group_b import agent
from test_sales_turn_1720 import case
from app.modules.sales_agent.understanding_contract import parse
from app.modules.sales_agent.understanding_prompt import TURN_RULES
from app.modules.sales_agent.commercial_composer import OPENINGS
from tools.sales_ai.evaluation_checks import internal_process_narration, turn_checks
from tools.sales_ai.evaluation_worker import VARIANT_CASES


DECLARATIONS = [
    ('Around 1,500,000 usd', 'budget', '1500000 USD'),
    ('My limit is 1.5 million dollars', 'budget', '1500000 USD'),
    ('USD 1500000 is my budget', 'budget', '1500000 USD'),
    ('I have a cash', 'financing', 'cash'),
    ('I can pay outright', 'financing', 'cash'),
    ('I have the funds to pay in full', 'financing', 'cash'),
    ('No, I said I have cash', 'financing', 'cash'),
    ('Actually, I will need a mortgage', 'financing', 'bank financing'),
    ("I don't have cash", 'financing', 'no cash'),
    ("I'd rather keep my budget private", 'budget', 'private'),
]


@pytest.mark.parametrize('text,key,value', DECLARATIONS)
def test_declarations_accept_exact_quotes_and_reject_fabricated_punctuation(text,key,value):
    u = understanding(text)
    data = u.model_dump(mode='json')
    data['preferences'] = [{'key':key,'value':value,'evidence':text,'status':'declared'}]
    assert parse(json.dumps(data),text).preferences[0].value == value
    data['preferences'][0]['evidence'] += '.'
    with pytest.raises(ValueError):parse(json.dumps(data),text)


@pytest.mark.parametrize('text', ['I have cash', 'I can pay in full', 'My budget is USD 1,500,000'])
def test_actual_repair_gets_current_turn_rules_and_recovers_without_customer_error(agent,text):
    good = understanding(text).model_dump(mode='json')
    good['preferences'] = [{'key':'financing' if 'budget' not in text else 'budget',
                           'value':text,'evidence':text,'status':'declared'}]
    bad = json.loads(json.dumps(good));bad['preferences'][0]['evidence'] += '.'
    agent.infer.side_effect = [json.dumps(bad),json.dumps(good)]
    _,run=agent.turn(text,json.dumps(bad))
    assert not run.error_code
    messages=agent.infer.await_args_list[-1].args[1]
    assert TURN_RULES in messages[0]['content']
    repair=json.loads(messages[-1]['content'])
    assert repair['exact_short_quote'] == text
    assert repair['validation_issues'][0]['type'] == 'evidence_mismatch'
    assert not internal_process_narration(agent.reply())


@pytest.mark.parametrize('text', ['Is parking included?', 'Does it have a garage?', 'Any parking spaces?'])
def test_specific_feature_contract_is_not_inventory(text):
    data=understanding(text,'property_details').model_dump(mode='json')
    data['requests'][0].update(detail_fields=['features'],feature='parking')
    u=parse(json.dumps(data),text)
    assert not u.permits('inventory')
    assert u.requests[0].detail_fields == ['features']


def test_linked_material_reference_must_be_local_not_a_database_identifier():
    text='Yes, send that brochure'
    data=understanding(text,'materials',subjects={0:'brochure'}).model_dump(mode='json')
    data['requests'][0]['reference_id']='asset-uuid'
    with pytest.raises(ValueError,match='Unknown reference'):parse(json.dumps(data),text)
    data['requests'][0]['reference_id']=None
    assert parse(json.dumps(data),text).permits('materials')


@pytest.mark.parametrize('text', ["I'm having trouble processing your message", "HTTPStatusError",
    "I couldn't prepare a reliable answer", 'Here is the information I could verify.'])
def test_evaluation_rejects_internal_narration(text):
    run=NS(output_snapshot={'workflow_version':'sales-current/1.0'},input_snapshot={},error_code=None)
    checks=turn_checks(run,text,None,{},0)
    assert next(c for c in checks if c['check']=='no_internal_process_narration')['status']=='FAIL'


def test_composer_helpful_opening_does_not_narrate_verification():
    assert OPENINGS['helpful']==''
    assert len(VARIANT_CASES)==9
    assert len({text for _,script in VARIANT_CASES for text,_ in script})==22


def test_repeated_failures_keep_internal_alert_and_customer_channel_open(agent):
    for index in range(3):
        agent.infer.side_effect=RuntimeError('provider detail must never reach customer')
        _,run=agent.turn('Please help with my property question '+str(index),'')
        assert not internal_process_narration(agent.reply())
        assert not run.output_snapshot['suppress_duplicate_error_reply']
        assert 'provider detail' not in agent.reply()
    assert not agent.conversation.is_paused


@pytest.mark.parametrize('text,key,value', DECLARATIONS[:9])
def test_current_engine_captures_declarations_with_evidence_and_without_loan_request(agent,text,key,value):
    from app.modules.sales_agent.lead_profile import resolve
    data=understanding(text).model_dump(mode='json')
    data['preferences']=[{'key':key,'value':value,'evidence':text,'status':'declared'}]
    _,run=agent.turn(text,json.dumps(data))
    assert not run.error_code
    record=resolve(agent.lead)['current'][key]
    assert record['status']=='declared'
    assert record['value']==text  # exact source, not an invented verified capability
    assert not internal_process_narration(agent.reply())
    assert not run.input_snapshot['understanding']['requests']


def test_wire_evidence_bound_changes_with_current_message_only():
    from app.modules.sales_agent.understanding_contract import response_schema
    schema=response_schema('I have cash')
    for name in ('Request','Preference','Reference'):
        assert schema['$defs'][name]['properties']['evidence']['maxLength']==len('I have cash')
    assert response_schema()['$defs']['Preference']['properties']['evidence']['maxLength']==2000
