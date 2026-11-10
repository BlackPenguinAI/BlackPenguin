"""Audited reference failures, turn-bound wire contract and real repair path."""
import json
import pytest
from app.modules.sales_agent import commercial_composer as c
from test_sales_composer_http import compose, strict


def evidence(n):
    return [{'id':f'e{i}','required':True,'wordings':dict(direct=f'Fact {i}.',conversational=f'Fact {i}.',natural=f'Fact {i}.')} for i in range(n)]


def plan(ids,paragraphs=None,continuation='none'):
    return c.Composition(version=c.VERSION,opening='direct',
        blocks=[c.BlockChoice(evidence_id=i,wording='direct') for i in ids],continuation_id=continuation,paragraphs=paragraphs or [])


@pytest.mark.parametrize('label,n,ids,paragraphs,rule',[
 ('greeting_profile_ids',0,['profile-budget','profile-financing'],[['Hello customer.']],'unknown_evidence'),
 ('catalog_prose_group',3,['e0','e1','e2'],[['Fact 0.','Fact 1.','Fact 2.']],'paragraph_reference'),
 ('catalog_prose_separate',3,['e0','e1','e2'],[['Fact 0.'],['Fact 1.'],['Fact 2.']],'paragraph_reference'),
 ('gallery_prose',1,['e0'],[['Gallery: [backend-issued-material-link]']],'paragraph_reference'),
 ('gallery_asset_ids',1,['gallery-asset-id','pdf-asset-id'],[['Gallery text']],'unknown_evidence'),
 ('financing_conversational',1,['e0'],[['The approved payment information is: Bank financing.']],'paragraph_reference'),
 ('financing_natural',1,['e0'],[['The listed payment options are: Bank financing.']],'paragraph_reference'),
 ('correction_extra_prose',1,['e0'],[['I appreciate your patience. Fact 0.']],'paragraph_reference'),
 ('correction_alternative_prose',1,['e0'],[['I understand your concern. Fact 0.']],'paragraph_reference'),
])
def test_nine_audited_failure_patterns(label,n,ids,paragraphs,rule):
    blocks=evidence(n); choices=[{'id':'none'}]; value=plan(ids,paragraphs)
    with pytest.raises(c.CompositionViolation) as caught:c.validate(value,blocks,choices)
    assert caught.value.code==rule
    diagnostic=c.validation_diagnostic(caught.value,value.model_dump_json(),blocks,choices)
    assert diagnostic['rule_code']==rule and diagnostic['validation_issues']
    example=c.repair_feedback(diagnostic,blocks,choices)['valid_example']
    c.validate(c.Composition.model_validate(example),blocks,choices)


def test_schema_enumerates_turn_ids_without_leaking_between_turns():
    schema=c.response_schema(evidence(3),[{'id':'priority'},{'id':'none'}]);strict(schema)
    assert schema['$defs']['BlockChoice']['properties']['evidence_id']['enum']==['e0','e1','e2']
    assert schema['properties']['paragraphs']['items']['items']['enum']==['e0','e1','e2']
    assert schema['properties']['continuation_id']['enum']==['priority','none']
    assert schema['properties']['blocks']['minItems']==schema['properties']['blocks']['maxItems']==3
    assert schema['properties']['paragraphs']['items']['minItems']==1
    assert 'enum' not in c.response_schema()['properties']['continuation_id']
    other=c.response_schema(evidence(1),[{'id':'clarify'}])
    assert other['properties']['continuation_id']['enum']==['clarify']
    assert other['$defs']['BlockChoice']['properties']['evidence_id']['enum']==['e0']


def test_empty_evidence_forces_empty_arrays_without_empty_enum():
    schema=c.response_schema([],[{'id':'courtesy'}]);strict(schema)
    assert schema['properties']['blocks']['maxItems']==0
    assert schema['properties']['paragraphs']['maxItems']==0
    def check(node):
        if isinstance(node,dict):
            assert node.get('enum')!=[]
            for value in node.values():check(value)
        elif isinstance(node,list):
            for value in node:check(value)
    check(schema)
    c.validate(plan([],continuation='courtesy'),[],[{'id':'courtesy'}])
    with pytest.raises(ValueError):c.response_schema([],[])


@pytest.mark.parametrize('ids,paragraphs,continuation,rule',[
 (['e0','e0'],[['e0','e0']],'none','duplicate_evidence'),
 ([],[],'none','missing_evidence'),
 (['e0'],[['e0']],'foreign','unauthorized_continuation'),
 (['e0'],[['e0','e0']],'none','paragraph_coverage'),
 (['e0'],[[]],'none','empty_paragraph'),
])
def test_semantic_guards_preserved(ids,paragraphs,continuation,rule):
    with pytest.raises(c.CompositionViolation) as caught:c.validate(plan(ids,paragraphs,continuation),evidence(1),[{'id':'none'}])
    assert caught.value.code==rule


def test_catalog_order_optional_blocks_and_default_grouping():
    blocks=evidence(3);blocks[0]['wordings']['direct']='1. First';blocks[1]['wordings']['direct']='2. Second';blocks[2]['required']=False
    choices=[{'id':'none'}]
    c.validate(plan(['e0','e1'],[['e0','e1']]),blocks,choices)
    c.validate(plan(['e0','e1'],[]),blocks,choices)
    with pytest.raises(c.CompositionViolation) as caught:c.validate(plan(['e1','e0'],[['e1','e0']]),blocks,choices)
    assert caught.value.code=='catalog_order'


def test_actual_compose_repairs_prose_with_rule_and_valid_turn_example(monkeypatch):
    calls=[]
    async def infer(model,messages,schema):
        calls.append(json.loads(json.dumps(messages)))
        assert schema['properties']['paragraphs']['items']['items']['enum']==['e0']
        assert schema['properties']['continuation_id']['enum']==['none']
        if len(calls)==1:return plan(['e0'],[['Private customer text must not be logged.']]).model_dump_json()
        feedback=json.loads(messages[-1]['content'])
        assert feedback['rule_code']=='paragraph_reference'
        assert feedback['allowed_evidence_ids']==feedback['required_evidence_ids']==['e0']
        assert feedback['allowed_continuation_ids']==['none']
        return json.dumps(feedback['valid_example'])
    result=compose(monkeypatch,infer)
    assert result.trace['status']=='accepted' and len(calls)==2
    assert result.trace['attempts'][0]['rule_code']=='paragraph_reference'
    assert result.trace['attempts'][1]['selection']['paragraphs']==[['e0']]
    assert 'Private customer text' not in json.dumps(result.trace)
    assert result.text=='Listed price: 1,394,900 USD.'


def test_schema_diagnostic_does_not_echo_unknown_values_or_field_names(monkeypatch):
    async def infer(*args):
        return json.dumps({'version':c.VERSION,'opening':'direct','blocks':[],
            'continuation_id':'none','paragraphs':'private-customer-data','private-key-field':'private-key-value'})
    result=compose(monkeypatch,infer)
    assert result.trace['status']=='safe_fallback'
    assert all(a['rule_code']=='schema_validation' for a in result.trace['attempts'])
    trace=json.dumps(result.trace)
    assert not any(s in trace for s in ('private-customer-data','private-key-field','private-key-value'))
    assert '__unknown_field__' in trace


def test_oversized_responses_keep_bounded_fallback(monkeypatch):
    async def infer(*args):return 'x'*17000
    result=compose(monkeypatch,infer)
    assert result.trace['status']=='safe_fallback' and len(result.trace['attempts'])==2
    assert all(a['rule_code']=='response_size' for a in result.trace['attempts'])
