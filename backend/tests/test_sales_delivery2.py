"""SA03/04 regression and real-coordinator checks, with scripted providers."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import pytest
from pydantic import ValidationError
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent,review
from test_sales_active_integration import understanding
from test_sales_ai_group_c import product,inbound,meeting
from test_sales_ai_group_d import typed,req,ref
from test_sales_ai_group_f import latest
from app.modules.sales_agent.understanding_contract import Understanding,Comparison,DialogueState,Constraint,PropertyConstraint
from app.modules.sales_agent.lead_profile import capture,resolve,optional_profile,qualification
from app.modules.sales_agent.turn_memory import build,booking_digest
from app.modules.sales_agent.dialogue_store import load,save
from app.modules.sales_agent.commercial_context import build_commercial_context
from app.modules.sales_agent.profile_intelligence import update
from app.modules.sales_agent.property_comparison import render,ComparisonRead,Target
from app.modules.sales_crm.models import LeadSegmentAssignment,Meeting
from app.modules.projects.models import ProjectUnit


def interpret(text,**changes):
    return Understanding.model_validate({**understanding(text).model_dump(),**changes}).check_evidence(text)


def capture_turn(agent,text,**changes):
    m=inbound(agent,text);result=capture(agent.db,agent.scope,interpret(text,**changes),m.id)
    agent.db.commit();return m,result


def context(agent):return build_commercial_context(agent.db,project=agent.project,company_id=agent.company.id,lead_id=agent.lead.id)


def score(agent,count=0):
    result=update(agent.db,agent.lead,commercial=context(agent),message_count=count)
    agent.db.commit();return result


def pref(key,text,**kw):return dict(key=key,value=text,evidence=text,**kw)


def compare(text,*,refs=(),criteria=('general',),current=False,all=False,operation='compare',selected=None,extra=()):
    u=typed(text,[req('compare','catalog',text),*extra],refs,selected=selected)
    return Understanding.model_validate({**u.model_dump(),'comparison':dict(request_id='compare',reference_ids=[r['id'] for r in refs],include_current=current,include_all=all,criteria=list(criteria),operation=operation,evidence=text)}).check_evidence(text)


def focus(agent,row):
    rev,state=load(agent.db,agent.scope);state.selected_property_type_id=row.id
    save(agent.db,agent.scope,event_key='focus:'+row.id,expected_revision=rev,state=state);agent.db.commit()


@pytest.mark.parametrize('shape',['flat','graph','source_answers'])
def test_optional_meta_separate_and_manual_lead_unknown(agent,shape):
    assert all(r['status']=='unknown' for r in optional_profile(agent.lead)['current'].values())
    values={'age':'35','occupation':'Teacher'}
    if shape=='flat':agent.lead.meta_form_data=values
    elif shape=='graph':agent.lead.meta_form_data={'field_data':[{'name':k,'values':[v]} for k,v in values.items()]}
    else:agent.lead.lead_profile_data={'source_answers':[{'key':k,'value':v} for k,v in values.items()]}
    agent.db.commit();p=optional_profile(agent.lead)
    assert p['current']['age']['value']=='35' and p['current']['occupation']['value']=='Teacher'
    assert 'age' not in resolve(agent.lead)['current']
    assert score(agent).total_score==0 and agent.lead.assigned_segment is None


def test_personal_correction_withdrawal_restart(agent):
    agent.lead.meta_form_data={'age':'35'};agent.db.commit()
    m,_=capture_turn(agent,'I am 36',personal_facts=[dict(key='age',action='set',evidence='I am 36')])
    old=optional_profile(agent.lead)['current']['age']
    assert old['value']=='I am 36' and old['source_ref']['message_id']==m.id
    capture_turn(agent,'Stop using my age',personal_facts=[dict(key='age',action='withdraw',evidence='Stop using my age')])
    agent.db.expire_all();row=optional_profile(agent.lead)['current']['age']
    assert row['status']=='withdrawn' and row['value'] is None and row['supersedes']==old['id']
    returned=inbound(agent,'What homes do you have')
    assert build(agent.db,agent.scope,inbound_message_id=returned.id)['optional_profile']['current']['age']['status']=='withdrawn'
    assert score(agent).factor_breakdown['financial_readiness']==0


@pytest.mark.parametrize('text',['My friend is a doctor','My partner is 35','Suppose I were a doctor','The agent said I am 35'])
def test_third_party_hypothetical_not_personal_profile(agent,text):
    capture_turn(agent,text,personal_facts=[dict(key='occupation',action='set',evidence=text)])
    assert optional_profile(agent.lead)['current']['occupation']['status']=='unknown'


def test_foreign_scope_and_false_evidence_no_writes(agent):
    m=inbound(agent,'I am a teacher');u=interpret(m.content,personal_facts=[dict(key='occupation',action='set',evidence=m.content)])
    before=deepcopy(agent.lead.lead_profile_data)
    with pytest.raises((PermissionError,ValueError)):capture(agent.db,replace(agent.scope,lead_id='foreign'),u,m.id)
    with pytest.raises(ValueError):capture(agent.db,agent.scope,u.model_copy(update={'personal_facts':[u.personal_facts[0].model_copy(update={'evidence':'I am a doctor'})]}),m.id)
    assert agent.lead.lead_profile_data==before


@pytest.mark.parametrize('field',['ethnicity','religion','health','income','birth_date','nationality','password'])
def test_personal_allowlist(field):
    with pytest.raises(ValidationError):interpret('private',personal_facts=[dict(key=field,action='set',evidence='private')])


def test_commercial_withdrawal_overrides_meta_and_no_reask(agent):
    agent.lead.meta_form_data={'budget':'200000 USD'};agent.db.commit()
    capture_turn(agent,'My budget is 300000 USD',preferences=[pref('budget','My budget is 300000 USD')])
    old=resolve(agent.lead)['current']['budget']
    capture_turn(agent,'Forget my budget',preference_withdrawals=[dict(key='budget',evidence='Forget my budget')])
    agent.db.expire_all();p=resolve(agent.lead)
    assert p['current']['budget']['status']=='withdrawn' and p['current']['budget']['value'] is None
    assert old['id'] in [r['id'] for r in p['history']]
    assert 'budget' not in qualification(agent.lead,{'qualification_rules':'Confirm budget range'})[0]
    assert 'budget' not in agent.lead.lead_profile_data['facts']
    assert score(agent).factor_breakdown['budget_fit']==0


@pytest.mark.parametrize('text',["I'd rather keep that private",'Please skip that question','I would rather not share my budget'])
def test_varied_refusals_declined(agent,text):
    capture_turn(agent,text,preferences=[pref('budget',text,status='declined')])
    assert resolve(agent.lead)['current']['budget']['status']=='declined'
    assert 'budget' not in qualification(agent.lead,{'qualification_rules':'Confirm budget range'})[0]
    assert score(agent).factor_breakdown['budget_fit']==0


def test_work_needs_are_explicit_not_inferred_from_occupation(agent):
    capture_turn(agent,'I am a teacher',personal_facts=[dict(key='occupation',action='set',evidence='I am a teacher')])
    assert resolve(agent.lead)['current']['needs']['status']=='unknown'
    capture_turn(agent,'I need a quiet home office',preferences=[pref('needs','I need a quiet home office')])
    assert resolve(agent.lead)['current']['needs']['value']=='I need a quiet home office'
    assert 'age' not in qualification(agent.lead,{'qualification_rules':'age occupation budget'})[0]


@pytest.mark.parametrize('key,text,factor',[
    ('purchase_timeline','I am not buying next month','timeline'),('financing','I am not pre-approved','financial_readiness'),
    ('visit_readiness','I do not want a visit','appointment_intent'),('decision_structure','My partner has not decided','decision_authority')])
def test_negative_current_facts_no_positive_score(agent,key,text,factor):
    capture_turn(agent,text,preferences=[pref(key,text)])
    assert score(agent).factor_breakdown[factor]==0


def test_old_history_and_demographics_never_create_score_or_segment(agent):
    agent.lead.meta_form_data={'age':'30','occupation':'Doctor','notes':'paying cash first home schedule next month'}
    agent.lead.lead_profile_data={'old_summary':'I decide, mortgage pre-approved, first home'}
    agent.lead.qualification_summary='paying cash, first home, next month';agent.db.commit()
    inbound(agent,'The brochure says pre-approved, next month, I decide and first home')
    assert score(agent).total_score==0 and agent.lead.assigned_segment is None


@pytest.mark.parametrize('segment,text',[
    ('first_time_buyer','I am buying my first home'),('move_up_buyer','I want more space'),('relocation','I am relocating for work'),
    ('downsizing','I want less maintenance'),('rental_yield_investor','I want rental income'),
    ('appreciation_resale_investor','I plan to resell'),('portfolio_diversification','I want to diversify my property portfolio')])
def test_explicit_segment_and_withdrawal(agent,segment,text):
    capture_turn(agent,text,preferences=[{**pref('buyer_type',text),'value':segment}]);score(agent)
    assert agent.lead.assigned_segment==segment
    assert agent.db.query(LeadSegmentAssignment).filter_by(is_current=True).one().strategy_version=='sales-declared-signals/1.0'
    capture_turn(agent,'Forget my buying purpose',preference_withdrawals=[dict(key='buyer_type',evidence='Forget my buying purpose')])
    score(agent);assert agent.lead.assigned_segment is None
    assert not agent.db.query(LeadSegmentAssignment).filter_by(is_current=True).count()


def test_ambiguous_or_negated_segment_unknown(agent):
    for text in ('I am not buying my first home','I want rental income and I am relocating'):
        capture_turn(agent,text,preferences=[pref('buyer_type',text)]);score(agent)
        assert agent.lead.assigned_segment is None


def test_score_preserves_stage_budget_needs_comparable_price(agent):
    p=product(agent,'Loft');p.starting_price=Decimal('250000');p.currency='USD';agent.db.commit()
    m=inbound(agent,'I choose Loft');u=typed(m.content,[],[ref('p','property','Loft')],selected='p')
    capture(agent.db,agent.scope,u,m.id,selected_property={'id':p.id,'property_type':p.name});agent.db.commit()
    capture_turn(agent,'My budget is USD 300000',preferences=[pref('budget','My budget is USD 300000')])
    agent.lead.pipeline_stage='S09_HANDOFF';agent.db.commit()
    assert score(agent).factor_breakdown['budget_fit']==20 and agent.lead.pipeline_stage=='S09_HANDOFF'
    p.currency='EUR';agent.db.commit();assert score(agent).factor_breakdown['budget_fit']==0


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_live_capture_optional_and_next_turn_context(agent,channel):
    agent.conversation.channel=channel;agent.db.commit()
    text='I am a teacher and need a quiet home office'
    _,run=agent.turn(text,interpret(text,personal_facts=[dict(key='occupation',action='set',evidence='I am a teacher')],preferences=[pref('needs','need a quiet home office')]))
    assert run.error_code is None,run.output_snapshot
    agent.db.expire_all();assert optional_profile(agent.lead)['current']['occupation']['value']=='I am a teacher'
    assert resolve(agent.lead)['current']['needs']['value']=='need a quiet home office'
    _,run=agent.turn('Show me property types',understanding('Show me property types','catalog'))
    assert run.error_code is None,run.output_snapshot
    payload=json.loads(agent.infer.call_args.args[1][1]['content'])
    assert payload['turn_context']['optional_profile']['current']['occupation']['status']=='declared'
    assert 'age' not in (latest(agent).metadata_json.get('qualification_offer') or {}).get('field','')


def samples():return [
    dict(id='a',property_type='Studio',bedrooms=2,bathrooms=1,area_min=100,area_max=100,area_unit='m2',starting_price=100000,maximum_price=100000,currency='USD',features=['Open kitchen'],available_units=0,inventory_updated_at='2030-01-01'),
    dict(id='b',property_type='Loft',bedrooms=3,bathrooms=2,area_min=1076.39104167,area_max=1076.39104167,area_unit='sq ft',starting_price=120000,maximum_price=120000,currency='USD',features=['Separate kitchen'],available_units=3,inventory_updated_at='2030-01-01')]


def rendered(rows,criteria=('general',),operation='compare',state=None,holds=()):
    d=Comparison(request_id='c',include_all=True,criteria=list(criteria),operation=operation,evidence='compare')
    return render(ComparisonRead(directive=d),{'property_types':rows,'inventory':[]},state or DialogueState(),set(holds))[0]


@pytest.mark.parametrize('criterion,op,winner',[('bedrooms','maximum','Loft'),('bathrooms','minimum','Studio'),('price','minimum','Studio'),('availability','maximum','Loft')])
def test_numeric_extrema(criterion,op,winner):
    assert f'{"highest" if op=="maximum" else "lowest"} {criterion} among these approved records: {winner}.' in rendered(samples(),[criterion],op)


def test_normalized_area_tie_missing_not_zero():
    rows=samples();assert 'Tie for highest area' in rendered(rows,['area'],'maximum')
    rows[1]['bedrooms']=None;text=rendered(rows,['bedrooms'],'minimum')
    assert 'unconfirmed' in text and 'cannot reliably rank' in text and 'lowest bedrooms among' not in text


@pytest.mark.parametrize('criterion,changes',[('price',{'currency':'EUR'}),('price',{'maximum_price':200000}),('area',{'area_unit':None}),('area',{'area_max':2000}),('availability',{'inventory_updated_at':None})])
def test_incomparable_or_ranges_no_winner(criterion,changes):
    rows=samples();rows[1].update(changes)
    assert 'cannot reliably rank' in rendered(rows,[criterion],'maximum')


def test_kitchen_and_features_concise():
    rows=samples();rows[1]['features']=[];rows[1]['description']='A loft. A kitchen island is included.'
    text=rendered(rows,['kitchen','bathrooms'])
    assert 'Open kitchen' in text and 'kitchen island' in text and 'bedrooms:' not in text


def test_global_and_property_specific_restrictions():
    state=DialogueState(constraints=[Constraint(topic='pricing',scope='until_explicit_change',evidence='no prices')],property_constraints=[PropertyConstraint(topic='property_details',scope='until_explicit_change',evidence='not Loft',property_id='b')])
    text=rendered(samples(),['price','bedrooms'],state=state)
    assert '100,000' not in text and '120,000' not in text
    assert 'Studio: price: held for Sales review; bedrooms: 2' in text
    assert 'Loft: price: held for Sales review; bedrooms: held for Sales review' in text
    assert '100,000' not in rendered(samples(),['price'],holds={'pricing'})


@pytest.mark.parametrize('criterion,op',[('general','maximum'),('kitchen','minimum'),('features','maximum')])
def test_subjective_winner_contract_rejected(criterion,op):
    with pytest.raises(ValidationError):Comparison(request_id='x',criteria=[criterion],operation=op,evidence='x')


@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_live_compare_current_other_keeps_focus_booking_and_idempotency(agent,channel):
    a=product(agent,'Studio');b=product(agent,'Loft');a.bedrooms=2;b.bedrooms=3;agent.conversation.channel=channel;agent.db.commit()
    focus(agent,a);booked=meeting(agent,product_id=a.id);before=booking_digest(booked)
    text='Compare Loft with my current choice on bedrooms'
    m,run=agent.turn(text,compare(text,refs=[ref('loft','property','Loft')],criteria=['bedrooms'],current=True))
    assert run.error_code is None,run.output_snapshot
    assert load(agent.db,agent.scope)[1].selected_property_type_id==a.id and booking_digest(booked)==before
    reply=agent.reply()
    assert 'Loft: bedrooms: 3' in reply and 'Studio: bedrooms: 2' in reply and 'Confirmed catalog:' not in reply
    offers=[v.metadata_json['property_catalog_offer'] for v in agent.db.query(__import__('app.modules.sales_agent.models',fromlist=['SalesMessage']).SalesMessage).all() if (v.metadata_json or {}).get('property_catalog_offer')]
    assert offers[-1]['property_type_ids']==[b.id,a.id]
    calls=agent.send.await_count;agent.retry(m)
    assert agent.send.await_count==calls and booking_digest(booked)==before


def test_all_compare_no_selection_explicit_switch_no_booking_change(agent):
    a=product(agent,'Studio');b=product(agent,'Loft');booked=meeting(agent,product_id=a.id);before=booking_digest(booked)
    text='Compare all homes';_,run=agent.turn(text,compare(text,all=True))
    assert run.error_code is None and load(agent.db,agent.scope)[1].selected_property_type_id is None
    text='Compare Studio with Loft and choose Loft'
    _,run=agent.turn(text,compare(text,refs=[ref('a','property','Studio'),ref('b','property','Loft')],selected='b'))
    assert run.error_code is None,run.output_snapshot
    assert load(agent.db,agent.scope)[1].selected_property_type_id==b.id and booking_digest(booked)==before


def test_mixed_comparison_financing_both_answered(agent):
    product(agent,'Studio');product(agent,'Loft');agent.project.profile.profile_data={'payment_methods':['Bank financing']}
    agent.project.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};agent.db.commit()
    text='Compare all homes and explain financing'
    _,run=agent.turn(text,compare(text,all=True,extra=[req('finance','financing',text)]))
    assert run.error_code is None,run.output_snapshot
    assert 'Studio:' in agent.reply() and 'Bank financing' in agent.reply()
    assert not agent.db.query(Meeting).count() and not agent.conversation.is_paused


def test_pricing_hold_cannot_be_bypassed_by_comparison(agent):
    a=product(agent,'Studio');b=product(agent,'Loft');a.starting_price=100000;b.starting_price=200000;a.currency=b.currency='USD';agent.db.commit()
    review(agent,rules=[dict(id='pricing-review',topics=['pricing'],effect='require_review',reason='Staff reviews pricing')])
    text='Compare all homes by price';_,run=agent.turn(text,compare(text,all=True,criteria=['price']))
    assert run.error_code is None,run.output_snapshot
    assert '100,000' not in agent.reply() and '200,000' not in agent.reply()


def test_unknown_target_not_silently_replaced(agent):
    product(agent,'Studio');product(agent,'Loft');text='Compare Unknown Home with Studio'
    _,run=agent.turn(text,compare(text,refs=[ref('a','property','Unknown Home'),ref('b','property','Studio')]))
    assert run.error_code is None,run.output_snapshot
    assert 'I need the property options' in agent.reply() and load(agent.db,agent.scope)[1].selected_property_type_id is None


def test_pending_comparison_survives_unrelated_turn_and_restart(agent):
    product(agent,'Studio');product(agent,'Loft')
    text='Compare Unknown Home with Studio on bathrooms'
    agent.turn(text,compare(text,refs=[ref('a','property','Unknown Home'),ref('b','property','Studio')],criteria=['bathrooms']))
    agent.db.expire_all();state=load(agent.db,agent.scope)[1]
    assert state.pending_comparison.criteria==['bathrooms']
    assert any(t.status=='awaiting_user' for t in state.tasks)
    agent.turn('Hello',understanding('Hello','other'))
    later=inbound(agent,'I meant Loft and Studio')
    memory=build(agent.db,agent.scope,inbound_message_id=later.id)
    assert memory['pending_comparison']['criteria']==['bathrooms']
    assert memory['pending_comparison_references'][0]['expression']=='Unknown Home'
    _,run=agent.turn(later.content,compare(later.content,refs=[ref('a','property','Loft'),ref('b','property','Studio')],criteria=['bathrooms']))
    assert run.error_code is None,run.output_snapshot
    assert load(agent.db,agent.scope)[1].pending_comparison is None


def test_budget_withdrawal_suppresses_all_legacy_aliases(agent):
    agent.lead.meta_form_data={'budget_min':100000,'budget_max':300000,'currency':'USD'};agent.db.commit()
    capture_turn(agent,'Forget my budget',preference_withdrawals=[dict(key='budget',evidence='Forget my budget')])
    assert all(resolve(agent.lead)['current'][f]['status']=='withdrawn' for f in ('budget','budget_minimum','budget_maximum','budget_currency'))
    assert all(resolve(agent.lead)['current'][f]['value'] is None for f in ('budget_minimum','budget_maximum','budget_currency'))


@pytest.mark.parametrize('raw,expected',[
    ({'budget':{'amount':200000,'currency':'USD'}},(200000,'USD')),
    ({'budget_max':300000,'currency':'USD'},(300000,'USD')),
    ({'budget':{'currency':'USD'}},None),({'budget':'USD 200000 or EUR 400000'},None),
    ({'budget':'between USD 200000 and 300000'},None),({'budget_max':True,'currency':'USD'},None)])
def test_budget_projection_requires_one_explicit_comparable_cap(agent,raw,expected):
    from app.modules.sales_agent.profile_intelligence import budget_cap
    agent.lead.meta_form_data=raw;agent.db.commit()
    assert budget_cap(resolve(agent.lead))==expected


def test_old_unproven_persona_not_used_in_guidance(agent):
    from app.modules.sales_agent.turn_configuration import resolve as guidance
    agent.lead.assigned_segment='downsizing';agent.lead.meta_form_data={'age':'70'};agent.db.commit()
    assert guidance(agent.db,agent.scope)['selection']['segment']['key'] is None
    assert agent.lead.assigned_segment=='downsizing'  # read-only until the next active turn.


def test_individual_units_compare_without_invented_area_dimensions():
    units=[dict(id='u1',unit_code='A101',property_type='Studio',area=80,bedrooms=1,bathrooms=1,price=100000,currency='USD'),
           dict(id='u2',unit_code='A102',property_type='Studio',area=90,bedrooms=2,bathrooms=2,price=120000,currency='USD')]
    d=Comparison(request_id='c',include_all=True,all_kind='unit',criteria=['area'],operation='maximum',evidence='compare')
    text,types,ids=render(ComparisonRead(directive=d),{'property_types':samples(),'inventory':units},DialogueState(),set())
    assert 'unit unconfirmed' in text and 'cannot reliably rank' in text
    assert ids==['u1','u2'] and types==[]
    d=d.model_copy(update={'criteria':['bedrooms']})
    text,_,_=render(ComparisonRead(directive=d),{'property_types':samples(),'inventory':units},DialogueState(),set())
    assert 'highest bedrooms among these approved records: Unit A102.' in text


def test_comparison_revalidates_revoked_target_instead_of_leaking_other_options():
    d=Comparison(request_id='c',criteria=['bedrooms'],evidence='compare')
    query=ComparisonRead(directive=d,targets=[Target(kind='property',property_id='a'),Target(kind='property',property_id='revoked')])
    text,ids,_=render(query,{'property_types':samples(),'inventory':[]},DialogueState(),set())
    assert ids==[] and 'no longer in the approved catalog' in text and 'bedrooms: 2' not in text


def test_multi_option_extremum_uses_all_records_not_only_displayed_first_twelve():
    rows=[{**samples()[0],'id':str(i),'property_type':'Option '+str(i),'bedrooms':i} for i in range(14)]
    text=rendered(rows,['bedrooms'],'maximum')
    assert 'Showing 12 of 14' in text and 'highest bedrooms among these approved records: Option 13.' in text


def test_requested_feature_is_not_lost_after_first_three_unrelated_tags():
    rows=samples();rows[0]['features']=['Parking','Storage','Terrace','Balcony'];rows[1]['features']=['Parking']
    d=Comparison(request_id='c',include_all=True,criteria=['features'],feature='balcony',evidence='Which has a balcony')
    text,_,_=render(ComparisonRead(directive=d),{'property_types':rows,'inventory':[]},DialogueState(),set())
    assert 'Studio: features: Balcony' in text and 'Loft: features: unconfirmed' in text
    assert 'Terrace' not in text and 'no balcony' not in text


@pytest.mark.parametrize('phrase,segment',[
    ('This would be my debut in home ownership','first_time_buyer'),
    ('I plan to let the home to tenants','rental_yield_investor'),
    ('We have outgrown our place and want a larger one','move_up_buyer')])
def test_semantic_purpose_normalization_keeps_exact_evidence_not_keyword_search(agent,phrase,segment):
    capture_turn(agent,phrase,preferences=[{**pref('buyer_type',phrase),'value':segment}])
    profile=resolve(agent.lead)['current']['buyer_type']
    assert profile['value']==phrase and profile['normalized_segment']==segment
    score(agent);assert agent.lead.assigned_segment==segment


def test_source_purpose_classification_is_bound_to_current_record_and_expires_on_correction(agent):
    agent.lead.meta_form_data={'buyer_type':'I plan to let the home to tenants'};agent.db.commit()
    row=resolve(agent.lead)['current']['buyer_type']
    assert agent.lead.assigned_segment is None
    capture_turn(agent,'Show me homes',source_purposes=[dict(field='buyer_type',record_id=row['id'],segment='rental_yield_investor')])
    score(agent);assert agent.lead.assigned_segment=='rental_yield_investor'
    agent.lead.meta_form_data={'buyer_type':'I am moving closer to work'};agent.db.commit()
    score(agent);assert agent.lead.assigned_segment is None
    capture_turn(agent,'Hello',source_purposes=[dict(field='buyer_type',record_id=row['id'],segment='rental_yield_investor')])
    score(agent);assert agent.lead.assigned_segment is None


def test_purpose_cannot_classify_demographic_record_or_reuse_personal_quote(agent):
    agent.lead.meta_form_data={'age':'70'};agent.db.commit()
    age=optional_profile(agent.lead)['current']['age']
    capture_turn(agent,'Hello',source_purposes=[dict(field='buyer_type',record_id=age['id'],segment='downsizing')])
    score(agent);assert agent.lead.assigned_segment is None
    text='I am 70'
    capture_turn(agent,text,preferences=[{**pref('buyer_type',text),'value':'downsizing'}],personal_facts=[dict(key='age',action='set',evidence=text)])
    score(agent);assert agent.lead.assigned_segment is None
    with pytest.raises(ValidationError):interpret('Hello',source_purposes=[dict(field='age',record_id=age['id'],segment='downsizing')])


def test_neutral_comparison_does_not_create_objection_and_explicit_ones_are_idempotent(agent):
    from app.modules.sales_crm.models import LeadObjection
    m=inbound(agent,'I cannot justify this expense')
    u=interpret(m.content,objections=[dict(kind='price',action='raise',evidence=m.content)])
    capture(agent.db,agent.scope,u,m.id);agent.db.commit()
    capture(agent.db,agent.scope,u,m.id);agent.db.commit()
    row=agent.db.query(LeadObjection).filter_by(lead_id=agent.lead.id).one()
    assert row.occurrence_count==1 and row.status=='open'
    capture_turn(agent,'Compare these properties')
    assert agent.db.query(LeadObjection).count()==1
    capture_turn(agent,'That resolves my price concern',objections=[dict(kind='price',action='resolve',evidence='That resolves my price concern')])
    assert row.status=='resolved' and not agent.conversation.is_paused


def test_current_published_scoring_weights_used_instead_of_draft(agent):
    from test_sales_ai_group_b import publish
    publish(agent,{**agent.config.agent_ventas,'scoring_config':{'engagement':1}})
    agent.config.agent_ventas={**agent.config.agent_ventas,'scoring_config':{'engagement':99}};agent.db.commit()
    _,run=agent.turn('Hello',understanding('Hello','other'))
    assert run.error_code is None,run.output_snapshot
    from app.modules.sales_crm.models import LeadScoreSnapshot
    assert agent.db.query(LeadScoreSnapshot).one().factor_breakdown['engagement']==1


def test_negative_or_ambiguous_semantic_labels_do_not_assign_segment(agent):
    capture_turn(agent,'I am not buying my first home',preferences=[{**pref('buyer_type','I am not buying my first home'),'value':'first_time_buyer'}])
    score(agent);assert agent.lead.assigned_segment is None
    capture_turn(agent,'I will move to a different city and buy to let',preferences=[
        {**pref('buyer_type','move to a different city'),'value':'relocation'},
        {**pref('motivation','buy to let'),'value':'rental_yield_investor'}])
    score(agent);assert agent.lead.assigned_segment is None


def test_unknown_unit_parent_cannot_bypass_property_specific_hold():
    state=DialogueState(property_constraints=[PropertyConstraint(topic='pricing',property_id='b',scope='until_explicit_change',evidence='no Loft prices')])
    units=[dict(id='u',unit_code='U',price=200000,currency='USD',typology=None)]
    d=Comparison(request_id='c',include_all=True,all_kind='unit',criteria=['price'],operation='minimum',evidence='compare')
    text,_,_=render(ComparisonRead(directive=d),{'property_types':samples(),'inventory':units},state,set())
    assert '200,000' not in text and 'cannot reliably rank' in text


def test_later_meta_enrichment_not_masked_by_empty_or_previous_source_projection(agent):
    capture_turn(agent,'Hello')
    agent.lead.meta_form_data={'age':'35','occupation':'Teacher'};agent.db.commit()
    assert optional_profile(agent.lead)['current']['age']['value']=='35'
    capture_turn(agent,'Show me homes')
    agent.lead.meta_form_data={'age':'36','occupation':'Architect'};agent.db.commit()
    assert optional_profile(agent.lead)['current']['occupation']['value']=='Architect'
    capture_turn(agent,'I am 37',personal_facts=[dict(key='age',action='set',evidence='I am 37')])
    agent.lead.meta_form_data={'age':'38','occupation':'Architect'};agent.db.commit()
    assert optional_profile(agent.lead)['current']['age']['value']=='I am 37'
