"""Commercial run 1 failures and independent positive/negative variants."""
import pytest
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.understanding_semantics import issues_for
from app.modules.sales_agent.understanding_repair import omit_declaration_questions,verified_preferences
from app.modules.sales_agent.financial_declarations import neutral_courtesy
from tools.sales_ai.commercial_pilot import quality_checks


@pytest.mark.parametrize('text',[
 'I have cash available and do not need financing.',
 "I have cash and don't need financing. What can you tell me about the property?",
 'I can pay in cash and do not require any financing. Show me the options.',
 'I will buy outright. What properties do you have?',
])
def test_cash_assertion_survives_unrelated_question_and_loan_negation(text):
    frame=understanding(text,'other')
    assert 'payment_declaration_missing' in {i['type'] for i in issues_for(frame,text)}


@pytest.mark.parametrize('text',[
 'I cannot pay cash.','My friend said I have cash available.',
 'If I have cash available, would that help?', 'Can I pay cash?',
])
def test_no_cash_preference_is_invented_from_negation_reporting_or_question(text):
    assert 'payment_declaration_missing' not in {i['type'] for i in issues_for(understanding(text,'other'),text)}


def test_run_one_cash_failure_requires_repair_and_drops_only_pure_false_question():
    text='My budget is 900,000 USD. I have cash available and do not need financing. What can you tell me about Bay Residence?'
    data=understanding(text,'financing','inventory').model_dump()
    data['requests'][0]['evidence']='I have cash available and do not need financing.'
    data['requests'][1]['evidence']='What can you tell me about Bay Residence?'
    frame=Understanding.model_validate(data)
    result,audit=omit_declaration_questions(frame,issues_for(frame,text))
    assert [r.topic.value for r in result.requests]==['inventory']
    assert 'payment_declaration_missing' in {i['type'] for i in issues_for(result,text)}
    assert audit


@pytest.mark.parametrize('phrase',['My total purchase budget is 250,000 USD.','My overall budget is 250000 USD.','My budget is 250000.50 USD.'])
def test_total_budget_is_not_a_financing_question(phrase):
    data=understanding(phrase,'financing').model_dump()
    data['preferences']=[dict(key='budget',value='250000 USD',evidence=phrase,status='declared')]
    frame=Understanding.model_validate(data)
    result,audit=omit_declaration_questions(frame,issues_for(frame,phrase))
    assert not result.requests and result.preferences==frame.preferences and audit


@pytest.mark.parametrize('phrase',[
 'No other questions, thank you. Goodbye.', 'Nothing else, thanks!',
 "That's all. Thank you for your help. Bye!", 'Thanks, have a nice day.',
])
def test_neutral_goodbyes_are_not_emotional_evidence(phrase):
    assert neutral_courtesy(phrase)
    data=understanding(phrase,'other').model_dump()
    data['empathy']={'kind':'frustrated','evidence':phrase}
    assert 'neutral_courtesy_as_emotion' in {i['type'] for i in issues_for(Understanding.model_validate(data),phrase)}


def test_genuine_emotion_and_real_financing_question_remain():
    text='I feel frustrated. What financing options do you offer?'
    data=understanding(text,'financing').model_dump();data['empathy']={'kind':'frustrated','evidence':'I feel frustrated.'}
    assert not issues_for(Understanding.model_validate(data),text)
    frame=understanding('Do you accept cash?','financing')
    assert omit_declaration_questions(frame,issues_for(frame,'Do you accept cash?'))[0]==frame


def test_new_quality_checks_detect_previous_unflagged_reply_errors():
    text='No other questions, thank you. Goodbye.'
    checks=quality_checks(text,"I understand this can feel frustrating. Goodbye.",{'empathy':{'kind':'frustrated'}})
    assert next(c for c in checks if c['check']=='no_emotion_invented_on_neutral_closure')['status']=='FAIL'
    sentence='The published payment information is: Cash; Bank financing.'
    checks=quality_checks('What financing is available?',sentence+' '+sentence,{})
    assert next(c for c in checks if c['check']=='payment_information_stated_once')['status']=='FAIL'
    assert next(c for c in checks if c['check']=='no_repeated_financial_sentences')['status']=='FAIL'


def test_verified_budget_is_not_lost_due_to_a_separate_no_loan_statement():
    text='My total purchase budget is 250,000 USD. I have cash available and do not need financing.'
    data=understanding(text,'other').model_dump();data['preferences']=[
        dict(key='budget',value='250000 USD',evidence='My total purchase budget is 250,000 USD',status='declared'),
        dict(key='financing',value='cash',evidence='I have cash available and do not need financing.',status='declared')]
    assert {p.key for p in verified_preferences(Understanding.model_validate(data),text)}=={'budget','financing'}



def test_cash_plus_independent_financing_question_is_preserved():
    text='I have cash available. What financing options do you offer?'
    data=understanding(text,'financing').model_dump();data['preferences']=[
        dict(key='financing',value='cash',evidence='I have cash available.',status='declared')]
    frame=Understanding.model_validate(data)
    assert issues_for(frame,text)==[]
    assert omit_declaration_questions(frame,issues_for(frame,text))[0]==frame


def test_property_question_does_not_make_cash_a_financing_request():
    text='I have cash available and do not need financing. What can you tell me about the property?'
    data=understanding(text,'financing').model_dump();data['preferences']=[
        dict(key='financing',value='cash',evidence='I have cash available and do not need financing.',status='declared')]
    assert 'declaration_as_question' in {i['type'] for i in issues_for(Understanding.model_validate(data),text)}
