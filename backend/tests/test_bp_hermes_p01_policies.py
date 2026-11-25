"""Portable conversation-policy regression; no live integrations used."""
from __future__ import annotations
from app.modules.hermes_sales_core import commercial_turn, conversation_context, sales_preferences, property_filters


def test_temporary_search_does_not_mutate_primary_preferences():
    state={'lead':{'budget_usd':200000,'min_bedrooms':2}}
    first=sales_preferences.apply(state,{'budget':{'mode':'cap','maximum_usd':200000},
        'bedrooms':{'mode':'preferred','preferred':2}},source_message_id='m1')
    assert first['ok'] and state['search_preferences']['revision']==1
    old=state['search_preferences'].copy()
    assert commercial_turn.search_request('Show me other homes with 3 bedrooms under my budget')
    assert commercial_turn.scope('Show me other homes with 3 bedrooms under my budget',has_primary=True)=='temporary'
    assert state['search_preferences']==old
    assert state['lead']['budget_usd']==200000


def test_explicit_budget_revision_overrides_cap_only():
    state={'lead':{}}
    sales_preferences.apply(state,{'budget':{'mode':'cap','maximum_usd':200000},
        'bedrooms':{'mode':'preferred','preferred':2}},source_message_id='m1')
    message="I don't want to spend more than $250k"
    parsed=sales_preferences.parse_declarations(message)
    assert parsed['budget']['mode']=='cap' and parsed['budget']['maximum_usd']==250000
    assert commercial_turn.scope(message,has_primary=True)=='permanent'
    result=sales_preferences.apply(state,parsed,source_message_id='m2')
    assert result['ok']
    assert state['lead']['budget_usd']==250000
    assert state['search_preferences']['bedrooms']['preferred']==2
    assert state['search_preferences']['revision']==2


def test_soft_target_not_misread_as_hard_cap():
    state={'lead':{}}
    out=sales_preferences.apply(state,{'budget':{'mode':'target','target_usd':200000}},source_message_id='m1')
    assert out['ok']
    assert state['search_preferences']['budget']['maximum_usd'] is None
    assert state['lead']['budget_usd'] is None


def test_maximum_budget_and_bedroom_hard_filters():
    p=sales_preferences.empty()
    p['budget'].update(mode='cap',maximum_usd=200000)
    p['bedrooms'].update(mode='minimum',minimum=2)
    assert sales_preferences.filter_unit({'price_usd':205000,'bedrooms':3},p)[0] is False
    assert sales_preferences.filter_unit({'price_usd':180000,'bedrooms':2},p)[0] is True


def test_property_detail_not_new_search():
    assert not commercial_turn.search_request('What is the price of H-201?')
    assert not commercial_turn.search_request('Show me photos of H-201')
    assert commercial_turn.search_request('Show me other 3-bedroom properties')
    assert commercial_turn.intent('Show me other homes') == 'property_search'


def test_focused_detail_vs_multiple_options_ambiguity():
    units={'H-201':{'area_sqm':100,'price_usd':190000},'H-202':{'area_sqm':90,'price_usd':185000}}
    state={'conversation_focus':{'unit_id':'H-201'},'last_presented_units':['H-201','H-202']}
    assert conversation_context.resolved_reference(state,'its area',units)['ambiguous'] is True
    assert conversation_context.resolved_reference(state,'What is the area of H-201?',units)['unit_id']=='H-201'


def test_single_focused_property_follow_up():
    units={'H-201':{'area_sqm':100,'price_usd':190000}}
    state={'conversation_focus':{'unit_id':'H-201'},'last_presented_units':['H-201']}
    resolution=conversation_context.resolved_reference(state,'What about its kitchen?',units)
    assert resolution['unit_id']=='H-201'
    assert conversation_context.topic('What about its kitchen?')=='kitchen'
    assert conversation_context.is_detail_question('What about its kitchen?')


def test_exploration_yes_not_booking_consent():
    assert conversation_context.is_property_confirmation('Yes', 'Would you like more details or continue exploring?')
    assert not conversation_context.is_property_confirmation('Yes', 'Can I book your appointment now?')


def test_comparative_filter_keeps_budget_separate():
    reference={'unit_id':'H-201','price_usd':190000,'bedrooms':2,'area_sqm':100}
    changes=property_filters.parse('Show me something cheaper than this house',reference=reference)
    assert changes['relative_price_lt']==190000
    assert 'maximum_usd' not in changes
    state={}
    assert property_filters.update(state,changes,'m1')['ok']
    listing={'area_sqm':90,'bathrooms':2,'price_usd':195000,'confirmed_features':{}}
    assert property_filters.matches(listing,state['property_filters'])


def test_state_modules_do_not_import_production_database_or_channels():
    from pathlib import Path
    from app.modules.hermes_sales_core import __file__ as location
    root=Path(location).parent
    modules=['runtime.py','contracts.py','commercial_turn.py','conversation_context.py',
             'sales_preferences.py','property_filters.py','contextual_choices.py']
    source='\n'.join((root/name).read_text(encoding='utf-8') for name in modules)
    assert 'from app.db.postgres' not in source
    assert 'import libsql' not in source
    assert 'from app.integrations.messaging_gateway' not in source
