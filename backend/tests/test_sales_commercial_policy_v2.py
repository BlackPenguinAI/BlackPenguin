"""Delivery 2: budget, published financing and visit-oriented information."""
from copy import deepcopy
from types import SimpleNamespace
from datetime import datetime
import pytest
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_ai_group_e import model
from test_sales_active_integration import understanding
from app.modules.sales_agent.commercial_policy import guidance,down_payment_only
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.understanding_repair import omit_unrelated_financial_preferences
from app.modules.sales_agent.lead_profile import resolve
from app.modules.sales_agent.request_safety import apply_vetoes
from app.modules.projects.models import ProjectPropertyType
from app.modules.sales_crm.models import Meeting,Lead


def buyer(budget=250000,currency='USD',financing=None):
    return Lead(meta_form_data={'budget':{'amount':budget,'currency':currency},**({'financing':financing} if financing else {})},
        lead_profile_data={},created_at=datetime.utcnow())


def context(payments=None):
    return {'confirmed_project_facts':{'payment_methods':payments or []},'inventory_source':'property_types',
        'property_types':[{'id':'loft','property_type':'Loft','starting_price':325000,'currency':'USD','available_units':5},
            {'id':'studio','property_type':'Studio','starting_price':210000,'currency':'USD','available_units':2}], 'inventory':[]}


def advise(text='What can I afford?',*,lead=None,commercial=None,selected=None,holds=(),u=None):
    return guidance(text=text,u=u or understanding(text,'pricing'),lead=lead or buyer(),commercial=commercial or context(),selected=selected,holds=holds)


@pytest.mark.parametrize('amount',[210000,250000,300000])
def test_affordable_alternative_uses_same_project_currency_and_approved_price(amount):
    result=advise(lead=buyer(amount),selected='loft')
    assert result['decision']=='within_budget_alternative' and result['alternative_ids']==['studio']
    assert '210,000.00 USD' in ' '.join(result['blocks'])
    assert 'need confirmation' in ' '.join(result['blocks'])


@pytest.mark.parametrize('bad',[
    {'available_units':0},{'starting_price':None},{'currency':'EUR'},{'starting_price':float('nan')},
])
def test_unknown_sold_out_currency_or_nonfinite_price_is_not_affordable_suggestion(bad):
    commercial=context();commercial['property_types'][1].update(bad)
    assert advise(commercial=commercial,selected='loft')['alternative_ids']==[]


@pytest.mark.parametrize('payment', ['Bank financing','Mortgage financing available'])
def test_lower_budget_can_discuss_published_financing_without_guarantee(payment):
    result=advise(lead=buyer(100000),commercial=context([payment]))
    assert result['decision']=='discuss_published_financing'
    text=' '.join(result['blocks'])
    assert payment in text and 'does not guarantee approval' in text and 'during an in-person visit' in text


@pytest.mark.parametrize('payment',[[],['Cash only'],['No financing available']])
def test_no_published_match_offers_other_questions_and_kind_close(payment):
    result=advise(lead=buyer(100000),commercial=context(payment))
    assert result['decision']=='no_budget_match'
    assert 'another question' in result['closing'] and 'good day' in result['closing']


def test_cash_preference_does_not_force_financing_for_insufficient_budget():
    result=advise(lead=buyer(100000,financing='paying cash'),commercial=context(['Cash','Bank financing']))
    assert result['decision']=='no_budget_match'


def test_no_currency_conversion_or_approval_from_lead_claim():
    result=advise(lead=buyer(300000,'EUR'))
    assert result['decision']=='currency_mismatch' and not result['alternative_ids']


@pytest.mark.parametrize('holds',[{'pricing'},{'catalog'},{'inventory'},{'property_details'}])
def test_held_commercial_facts_cannot_be_reintroduced_as_alternatives(holds):
    assert not advise(holds=holds)['alternative_ids']


@pytest.mark.parametrize('phrase', ['I have 50000 USD for a down payment','My deposit budget is 50000 USD','I can put 50000 USD towards the initial contribution'])
def test_down_payment_does_not_become_total_budget(phrase):
    data=understanding(phrase,'financing').model_dump()
    data['preferences']=[dict(key='budget',value='50000 USD',evidence=phrase,status='declared')]
    result,audit=omit_unrelated_financial_preferences(Understanding.model_validate(data))
    assert not result.preferences and audit[0]['reason']=='down_payment_as_total_budget'
    result=advise(phrase,u=result)
    assert result['decision']=='clarify_total_budget' and 'total purchase budget' in result['closing']


@pytest.mark.parametrize('text',['Can I reserve this property?','I want to pay the deposit for the apartment','How can I transfer money to hold the unit?'])
def test_property_reservation_never_authorizes_an_appointment(text):
    value=apply_vetoes(understanding(text,'appointment'),text)
    assert any(c.topic.value=='appointment' and c.scope=='turn' for c in value.constraints)
    result=advise(text,u=value)
    assert 'cannot take a payment or hold a property' in ' '.join(result['blocks'])


def test_visit_and_commercial_reservation_are_independent():
    text='Can I reserve the property? I would also like a visit.'
    assert not apply_vetoes(understanding(text,'appointment'),text).constraints


def test_individual_units_use_exact_available_unit_prices():
    commercial=context();commercial.update(inventory_source='individual_units',inventory=[
        dict(id='u1',unit_code='A-1',property_type_id='loft',price=200000,currency='USD',status='available'),
        dict(id='u2',unit_code='A-2',property_type_id='loft',price=100000,currency='USD',status='sold')])
    result=advise(commercial=commercial)
    assert result['alternative_ids']==['u1'] and 'A-1' in ' '.join(result['blocks'])


def test_unpublished_financing_does_not_appear(agent,model):
    agent.project.profile.profile_data={'payment_methods':['Draft promise of zero down']}
    agent.project.profile.field_states={'payment_methods':{'status':'pending'}};agent.db.commit()
    _,run=agent.turn('What financing and down payment options do you offer?',understanding('What financing and down payment options do you offer?','financing'))
    assert run.error_code is None
    assert 'zero down' not in agent.reply() and 'do not have published' in agent.reply()
    assert 'during an in-person visit' in agent.reply()


def test_real_coordinator_suggests_affordable_type_and_does_not_book(agent,model):
    agent.lead.meta_form_data={'budget':{'amount':250000,'currency':'USD'}}
    for name,price in [('Loft',325000),('Studio',210000)]:
        agent.db.add(ProjectPropertyType(project_id=agent.project.id,name=name,starting_price=price,currency='USD',review_status='confirmed',available_units=2,inventory_updated_at=datetime.utcnow()))
    agent.db.commit()
    _,run=agent.turn('What property fits my budget?',understanding('What property fits my budget?','pricing'))
    assert run.error_code is None and 'within your stated total budget' in agent.reply()
    assert 'more details about one of these options' in agent.reply()
    assert agent.db.query(Meeting).count()==0


@pytest.mark.parametrize('raw',['250000','USD 200000 or EUR 300000'])
def test_ambiguous_budget_requests_currency_and_total_instead_of_guessing(raw):
    lead=buyer();lead.meta_form_data={'budget':raw}
    result=advise(lead=lead)
    assert result['decision']=='clarify_budget_currency' and not result['alternative_ids']


def test_financing_question_does_not_require_a_budget_or_redefine_a_deposit():
    result=advise('What are the down payment terms?',u=understanding('What are the down payment terms?','financing'))
    assert result['decision']!='clarify_total_budget'
    assert 'during an in-person visit' in ' '.join(result['blocks'])


@pytest.mark.parametrize('selected',['loft','u2'])
def test_selected_individual_unit_or_named_type_still_finds_affordable_unit(selected):
    commercial=context();commercial.update(inventory_source='individual_units',inventory=[
        dict(id='u1',unit_code='A-1',property_type='Loft',price=200000,currency='USD',status='available'),
        dict(id='u2',unit_code='A-2',property_type='Loft',price=300000,currency='USD',status='available')])
    assert advise(commercial=commercial,selected=selected)['alternative_ids']==['u1']



def test_no_need_for_financing_does_not_negate_a_separately_declared_budget():
    from app.modules.sales_agent.profile_intelligence import budget_cap
    lead=buyer();lead.meta_form_data={'budget':'My budget is 250000 USD. I do not need financing.'}
    assert budget_cap(resolve(lead))==(250000,'USD')
    lead.meta_form_data={'budget':'My budget is not 250000 USD. I do not need financing.'}
    assert budget_cap(resolve(lead)) is None
