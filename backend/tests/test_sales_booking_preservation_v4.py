"""Preserve verified current declarations without copying rejected business actions."""
import json
from types import SimpleNamespace as NS
import pytest
from app.modules.sales_agent.understanding_contract import Understanding,parse,decode
from app.modules.sales_agent.understanding_repair import verified_preferences,preserve_preferences
from app.modules.sales_agent.understanding_semantics import issues_for
from app.modules.sales_agent.planning_reply import continuation
from test_sales_active_integration import understanding

TEXT='I would like a visit. My budget is 900,000 USD, paying cash.'


def budget_frame(text=TEXT,value='900000 USD'):
    data=understanding(text,'appointment').model_dump()
    data['preferences']=[{'key':'budget','value':value,'evidence':'My budget is 900,000 USD','status':'declared'}]
    return Understanding.model_validate(data)


def test_restore_independently_verified_budget_only():
    original=budget_frame();preserved=verified_preferences(original,TEXT)
    assert [p.key for p in preserved]==['budget']
    repaired=understanding(TEXT,'appointment')
    result,audit=preserve_preferences(repaired,preserved)
    assert result.preferences==original.preferences and result.requests==repaired.requests
    assert result.references==repaired.references and result.visit==repaired.visit
    assert audit==[{'field':'budget','action':'restore_verified_current_declaration','source_attempt':1}]
    assert parse(result.model_dump_json(),TEXT)==result


@pytest.mark.parametrize('suffix',[' My friend said this.',' Forget my budget.',' If I could afford it.'])
def test_no_preservation_of_ambiguous_or_withdrawn_declaration(suffix):
    assert verified_preferences(budget_frame(TEXT+suffix),TEXT+suffix)==[]


def test_never_restore_invented_amount_or_overwrite_withdrawal():
    assert verified_preferences(budget_frame(value='950000 USD'),TEXT)==[]
    valid=verified_preferences(budget_frame(),TEXT)
    data=understanding(TEXT,'other').model_dump();data['preference_withdrawals']=[{'key':'budget','evidence':'My budget is 900,000 USD'}]
    frame=Understanding.model_validate(data)
    restored,audit=preserve_preferences(frame,valid)
    assert restored==frame and not audit


def test_structural_diagnostics_can_find_cash_error_even_when_quote_is_wrong():
    data=budget_frame().model_dump();data['requests'][0]['evidence']='I would like to book a visit.'
    raw=json.dumps(data)
    with pytest.raises(ValueError):parse(raw,TEXT)
    assert 'payment_declaration_missing' in {i['type'] for i in issues_for(decode(raw),TEXT)}


def test_budget_is_not_an_inventory_question():
    data=budget_frame().model_dump();data['requests'][0]['topic']='inventory';data['requests'][0]['evidence']='My budget is 900,000 USD, paying cash.'
    assert 'budget_declaration_as_question' in {i['type'] for i in issues_for(Understanding.model_validate(data),TEXT)}


def test_waiting_for_availability_is_not_lack_of_lead_readiness():
    state=NS(wait_context={'id':'wait'},last_understanding=understanding('Thanks','other'))
    text,_=continuation(NS(plan={'pending_topics':['appointment']},state=state,stop_reason='complete'),set())
    assert 'new viewing times' in text and "when you're ready" not in text



def test_pure_budget_inventory_pseudoquestion_is_omitted_without_changing_visit():
    from app.modules.sales_agent.understanding_repair import omit_declaration_questions
    data=budget_frame().model_dump();q=dict(data['requests'][0]);q.update(id='extra',topic='inventory',evidence='My budget is 900,000 USD, paying cash.')
    data['requests'].append(q);data['all_of'].append('extra')
    value=Understanding.model_validate(data)
    fixed,audit=omit_declaration_questions(value,issues_for(value,TEXT))
    assert fixed.requests==value.requests[:1] and fixed.preferences==value.preferences
    assert fixed.all_of==value.all_of[:1] and audit[0]['action']=='omit_question_invented_from_declaration'
    assert fixed.visit==value.visit and fixed.constraints==value.constraints
    q['evidence']='My budget is 900,000 USD, paying cash. What properties are available?'
    data['requests'][-1]=q;value=Understanding.model_validate(data)
    assert omit_declaration_questions(value,issues_for(value,TEXT))[0]==value
