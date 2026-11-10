"""Exercise the real HTTP client boundary without contacting a provider."""
import asyncio
import json
from types import SimpleNamespace as NS
import httpx
import pytest
from app.modules.sales_agent import commercial_composer as composer


def strict(schema):
    if isinstance(schema, dict):
        assert 'default' not in schema
        if schema.get('type') == 'object':
            assert set(schema['required']) == set(schema.get('properties', {}))
            assert schema['additionalProperties'] is False
        for value in schema.values(): strict(value)
    elif isinstance(schema, list):
        for value in schema: strict(value)


def error(status, payload):
    r = httpx.Response(status, json=payload, request=httpx.Request('POST', 'https://openrouter.ai/api/v1/chat/completions'))
    return httpx.HTTPStatusError('not persisted', request=r.request, response=r)


def test_schema_is_closed_and_local_defaults_unchanged():
    original = composer.Composition.model_json_schema()
    assert 'paragraphs' not in original['required']
    strict(composer.response_schema())
    assert 'paragraphs' in composer.response_schema()['required']
    assert composer.Composition.model_json_schema() == original
    assert composer.Composition(version=composer.VERSION, opening='direct', blocks=[], continuation_id='none').paragraphs == []


@pytest.mark.parametrize('status,category', [(401,'authentication'), (402,'insufficient_credit'),
    (403,'permission'), (429,'rate_limit'), (503,'upstream_failure')])
def test_http_error_classification_never_persists_provider_body(status, category):
    details = composer.provider_error_details(error(status, {'error': {'message': 'secret-key private lead'}}))
    assert details == {'http_status':status, 'provider_error_category':category}


def test_nested_schema_error_is_sanitized():
    details = composer.provider_error_details(error(400, {'error': {'metadata': {
        'raw': 'Invalid schema: required must include paragraphs. secret-key private lead'}}}))
    assert details == {'http_status':400, 'provider_error_category':'structured_output_schema',
                       'schema_fields_mentioned':['paragraphs']}
    assert composer.provider_error_details(TimeoutError()) == {}


def compose(monkeypatch, infer):
    from app.modules.sales_agent import turn_memory
    monkeypatch.setattr(composer, 'resolve', lambda *a: {'model':'openai/gpt-4o-mini','source':{},'selection':{}})
    monkeypatch.setattr(turn_memory, 'build', lambda *a, **kw: {'appointments':{'active':{'count':0}}})
    monkeypatch.setattr(composer, 'select_continuations', lambda **kw: [{'id':'none','text':'','metadata':{}}])
    return asyncio.run(composer.compose(None, None, inbound=NS(id='synthetic',content='Listed price?'),
        outcome=NS(state=NS(last_understanding=NS(requests=[],empathy=None)),results=[],plan={}),
        draft=NS(text='Listed price: 1,394,900 USD.'),commercial={'confirmed_project_facts':{},'property_types':[]},
        lead=None,metadata={},previous_meta={},holds=[],channel='whatsapp',infer=infer))


def test_real_http_boundary_rejects_legacy_schema_and_accepts_fixed_composition(monkeypatch):
    from app.integrations.openrouter_client import generate_llm_response
    seen=[]
    def provider(request):
        schema=json.loads(request.content)['response_format']['json_schema']['schema'];seen.append(schema)
        try: strict(schema)
        except AssertionError:
            return httpx.Response(400,json={'error':{'message':'Invalid schema: required must include paragraphs'}})
        body={'version':composer.VERSION,'opening':'direct','blocks':[{'evidence_id':'e0','wording':'natural'}],
              'continuation_id':'none','paragraphs':[['e0']]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(body)}}]})
    client=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(provider),**kw))
    async def infer(model,prompts,schema):
        return await generate_llm_response('synthetic-key',model,prompts,response_format={'type':'json_schema',
            'json_schema':{'name':'sales_commercial_composition','strict':True,'schema':schema}},raise_on_error=True)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(infer('openai/gpt-4o-mini',[],composer.Composition.model_json_schema()))
    assert exc.value.response.status_code==400
    result=compose(monkeypatch,infer)
    assert result.trace['status']=='accepted'
    assert result.text=='Listed price: 1,394,900 USD.' and len(seen)==2


def test_actual_composition_records_status_and_retains_safe_fallback(monkeypatch):
    async def infer(*args):
        raise error(400,{'error':{'message':'Invalid schema required paragraphs secret-key private lead'}})
    result=compose(monkeypatch,infer);attempt=result.trace['attempts'][0]
    assert result.trace['status']=='safe_fallback' and len(result.trace['attempts'])==1
    assert attempt['http_status']==400 and attempt['error_code']=='HTTPStatusError'
    assert attempt['provider_error_category']=='structured_output_schema'
    assert 'secret-key' not in json.dumps(result.trace)
    assert result.text=='Listed price: 1,394,900 USD.'


def test_unknown_evidence_is_still_rejected(monkeypatch):
    async def infer(*args):
        return json.dumps({'version':composer.VERSION,'opening':'direct','blocks':[{'evidence_id':'invented','wording':'natural'}],
            'continuation_id':'none','paragraphs':[['invented']]})
    result=compose(monkeypatch,infer)
    assert result.trace['status']=='safe_fallback' and len(result.trace['attempts'])==2
    assert all(a['status']=='invalid_contract' for a in result.trace['attempts'])
    assert 'invented' not in result.text


def test_synthetic_probe_validates_output_without_usage_persistence(monkeypatch):
    from tools.sales_ai import probe_composition as probe
    captured=[]
    async def generate(key, model, messages, **kw):
        captured.append(kw)
        return messages[1]['content']
    monkeypatch.setattr(probe, 'generate_llm_response', generate)
    result=asyncio.run(probe.probe('synthetic-key','openai/gpt-4o-mini',composer.response_schema(),'corrected'))
    assert result == {'schema':'corrected','result':'accepted','http_status':200}
    assert 'usage_context' not in captured[0]
    assert captured[0]['max_tokens']==256
    assert 'synthetic-key' not in json.dumps(result)
