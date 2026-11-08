"""Scoped references and result-driven bounded planning; providers are mocked."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
import pytest
from test_sales_turn_1720 import case,approved_asset,outbound
from test_sales_ai_group_b import agent
from test_sales_ai_group_c import product,meeting,inbound
from test_sales_active_integration import understanding
from app.modules.sales_agent.understanding_contract import Understanding,Reference,DialogueState,Task,Offer,PropertyConstraint
from app.modules.sales_agent.dialogue_store import load,save,DialogueConflict
from app.modules.sales_agent.dialogue_orchestrator import run_turn
from app.modules.sales_agent.dialogue_tools import ReadTools,ToolCall
from app.modules.sales_agent.reference_resolution import Resolver,offers_for_turn
from app.modules.sales_agent.turn_memory import booking_digest
from app.modules.sales_agent.models import SalesMessage
from app.modules.projects.models import ProjectPropertyType,ProjectUnit,SalesAssetShare
from app.modules.sales_crm.models import Meeting
from app.core.config import settings


def typed(text,requests,refs=(),*,alternatives=(),selected=None,constraints=()):
    data=dict(version='sales-understanding/1.0',requests=requests,all_of=[r['id'] for r in requests if r['polarity']=='request' and not any(r['id'] in g['request_ids'] for g in alternatives)],
        alternatives=list(alternatives),constraints=list(constraints),references=list(refs),preferences=[],requires_clarification=False,
        clarification_question=None,confidence=.99,selected_reference_id=selected)
    return Understanding.model_validate(data).check_evidence(text)


def req(id,topic,evidence,*,ref=None,subject=None,polarity='request'):
    return dict(id=id,topic=topic,evidence=evidence,reference_id=ref,subject=subject,polarity=polarity)


def ref(id,kind,expression):return dict(id=id,kind=kind,expression=expression,evidence=expression)


def run(agent,text,u,**limits):
    row=inbound(agent,text);revision,_=load(agent.db,agent.scope)
    value=run_turn(agent.db,agent.scope,message_id=row.id,understanding=u,expected_revision=revision,event_key='test:'+row.id,**limits)
    agent.db.commit();return row,value


def catalog_offer(agent,rows):
    return outbound(agent.db,agent.conversation,'\n'.join(f'{i}. {p.name}' for i,p in enumerate(rows,1)),{'property_catalog_offer':{'property_type_ids':[p.id for p in rows]}})


def resolver(agent):
    revision,state=load(agent.db,agent.scope)
    state.offers=offers_for_turn(agent.db,agent.conversation,state)
    return Resolver(agent.db,agent.scope,state),state


@pytest.mark.parametrize('expression',['Studio','STUDIO','Studio '])
def test_names_are_exact_approved_matches(agent,expression):
    row=product(agent,'Studio');r,_=resolver(agent)
    result=r.resolve(Reference(kind='property',expression=expression,evidence=expression))
    assert result['value']['id']==row.id


def test_unapproved_or_unknown_name_does_not_change_interest(agent):
    product(agent,'Studio')
    agent.db.add(ProjectPropertyType(project=agent.project,name='Private type',review_status='pending'));agent.db.commit()
    text='Tell me about Private type'
    _,run_result=agent.turn(text,typed(text,[req('details','property_details',text,ref='p')],[ref('p','property','Private type')]))
    assert not load(agent.db,agent.scope)[1].selected_property_type_id
    assert run_result.output_snapshot['metadata']['reference_question'] and not agent.conversation.is_paused


def test_ordinal_uses_delivered_order_after_catalog_reordering(agent):
    a=product(agent,'Studio');b=product(agent,'Loft');catalog_offer(agent,[b,a])
    a.sort_order=-10;b.sort_order=99;agent.db.commit()
    r,_=resolver(agent)
    assert r.resolve(Reference(kind='property',expression='the second property',evidence='the second property'))['value']['id']==a.id


@pytest.mark.parametrize('count',[2,3])
def test_other_property_selects_only_when_unique(agent,count):
    rows=[product(agent,name) for name in ('Studio','Loft','Penthouse')[:count]];catalog_offer(agent,rows)
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=rows[0].id
    save(agent.db,agent.scope,event_key='select',expected_revision=revision,state=state);agent.db.commit()
    r,_=resolver(agent);result=r.resolve(Reference(kind='property',expression='the other one',evidence='the other one'))
    if count==2:assert result['value']['id']==rows[1].id
    else:assert result['status']=='clarification' and {o['id'] for o in result['options']}=={p.id for p in rows[1:]}


def test_bare_property_number_never_revives_suspended_slot(agent):
    a=product(agent);slot=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    old=outbound(agent.db,agent.conversation,'Choose a time',{'appointment_offer':{'slots':[slot]}})
    revision,state=load(agent.db,agent.scope);state.offers=[Offer(kind='appointment',message_id=old.id,option_ids=[slot],expires_at=datetime.now(timezone.utc)+timedelta(minutes=20))]
    save(agent.db,agent.scope,event_key='slot',expected_revision=revision,state=state);agent.db.commit();catalog_offer(agent,[a])
    r,state=resolver(agent)
    assert r.resolve(Reference(kind='appointment',expression='1',evidence='1'))['status']=='clarification'
    assert r.resolve(Reference(kind='property',expression='1',evidence='1'))['value']['id']==a.id


def test_partial_multipart_offer_and_manual_reply_are_not_ordinal_authority(agent):
    a=product(agent)
    row=catalog_offer(agent,[a]);row.metadata_json={**row.metadata_json,'delivery_group':{'key':'incomplete','part':1,'total':2}};agent.db.commit()
    r,_=resolver(agent)
    assert r.resolve(Reference(kind='property',expression='1',evidence='1'))['status']=='clarification'
    human=outbound(agent.db,agent.conversation,'A human follow-up');human.role='human';agent.db.commit()
    assert resolver(agent)[1].offers==[]


def test_expired_slot_is_not_renewed_when_interrupting(agent):
    row=outbound(agent.db,agent.conversation,'Choose a time')
    slot=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    state=DialogueState(offers=[Offer(kind='appointment',message_id=row.id,option_ids=[slot],expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))])
    assert offers_for_turn(agent.db,agent.conversation,state)==[]


def test_comparison_requests_bind_independently_without_selecting_last_property(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    text='Compare Studio and Loft'
    _,outcome=run(agent,text,typed(text,[req('a','property_details',text,ref='a'),req('b','property_details',text,ref='b')],[ref('a','property','Studio'),ref('b','property','Loft')]))
    assert outcome.state.selected_property_type_id is None
    assert [r.data['property_types'][0]['id'] for r in outcome.results]==[a.id,b.id]
    assert len(outcome.plan['request_coverage'])==2


def test_explicit_focus_updates_interest_without_changing_existing_booking(agent):
    a=product(agent,'Studio');b=product(agent,'Loft');visit=meeting(agent,product_id=a.id);before=booking_digest(visit)
    text='Compare Studio and Loft; I choose Loft'
    agent.turn(text,typed(text,[req('a','property_details',text,ref='a'),req('b','property_details',text,ref='b')],
        [ref('a','property','Studio'),ref('b','property','Loft')],selected='b'))
    assert load(agent.db,agent.scope)[1].selected_property_type_id==b.id and booking_digest(visit)==before


def test_ambiguous_material_reference_does_not_block_financing(agent):
    product(agent,'Studio');product(agent,'Loft')
    agent.project.profile.profile_data={'payment_methods':['Bank financing']}
    agent.project.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};agent.db.commit()
    text='Send plans for the other one and explain financing'
    _,run_result=agent.turn(text,typed(text,[req('plans','materials',text,ref='p',subject='floor_plan'),req('finance','financing',text)],
        [ref('p','property','the other one')]))
    assert 'Bank financing' in agent.reply() and 'Which property option' in agent.reply()
    assert not agent.db.query(SalesAssetShare).count() and not agent.conversation.is_paused


def test_property_clarification_resumes_original_plans_request(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan']);asset.property_type_id=b.id;agent.db.commit()
    text='Send plans for the other one'
    agent.turn(text,typed(text,[req('plans','materials',text,ref='p',subject='floor_plan')],[ref('p','property','the other one')]))
    assert not agent.db.query(SalesAssetShare).count()
    agent.turn('Loft',typed('Loft',[req('choice','property_details','Loft',ref='p')],[ref('p','property','Loft')]))
    assert agent.db.query(SalesAssetShare).one().sales_asset_id==asset.id


def test_unit_selection_uses_approved_unit_code_and_relevant_material_coverage(agent):
    a=product(agent,'Studio')
    unit=ProjectUnit(project=agent.project,unit_code='A-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow(),bedrooms=2)
    agent.db.add(unit);agent.db.commit()
    text='Tell me about A-101'
    agent.turn(text,typed(text,[req('details','property_details',text,ref='u')],[ref('u','unit','A-101')]))
    state=load(agent.db,agent.scope)[1]
    assert state.selected_unit_id==unit.id and state.selected_property_type_id==a.id and 'Unit A-101' in agent.reply()


def test_unit_without_known_parent_is_recorded_without_inventing_typology_or_reasking_interest(agent):
    from app.modules.sales_agent.lead_profile import resolve,qualification
    unit=ProjectUnit(project=agent.project,unit_code='U-101',typology=None,status='available',inventory_updated_at=datetime.utcnow())
    agent.db.add(unit);agent.db.commit()
    text='Tell me about U-101'
    agent.turn(text,typed(text,[req('details','property_details',text,ref='u')],[ref('u','unit','U-101')]))
    state=load(agent.db,agent.scope)[1]
    assert state.selected_unit_id==unit.id and state.selected_property_type_id is None
    assert resolve(agent.lead)['current']['property_interest']['value']=='U-101'
    assert qualification(agent.lead,{'qualification_rules':'property type'})[0]==[]
    assert 'Unit U-101' in agent.reply()


def test_scoped_photo_exclusion_does_not_block_other_property(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    assets={}
    for p in (a,b):
        asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['gallery_image'],name=p.name+' photos');asset.property_type_id=p.id
        assets[p.id]=asset
    agent.db.commit()
    text='Send Studio photos, not Loft photos'
    _,run_result=agent.turn(text,typed(text,[req('a','materials','Send Studio photos',ref='a',subject='photos'),req('b','materials','not Loft photos',ref='b',subject='photos',polarity='exclude')],
        [ref('a','property','Studio'),ref('b','property','Loft')]))
    assert agent.db.query(SalesAssetShare).count()==1,run_result.output_snapshot
    assert agent.db.query(SalesAssetShare).one().sales_asset_id==assets[a.id].id


def test_or_fallback_tries_distributable_alternative_before_offering_uncertain_photos(agent):
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure'])
    text='Send photos or a brochure'
    _,result=agent.turn(text,typed(text,[req('photos','materials',text,subject='photos'),req('pdf','materials',text,subject='brochure')],
        alternatives=[dict(id='choice',request_ids=['photos','pdf'],evidence=text)]))
    assert agent.db.query(SalesAssetShare).count()==1 and not result.output_snapshot['metadata'].get('material_offer'),result.output_snapshot


@pytest.mark.parametrize('limit_kind',['step','time','cost'])
def test_budget_limits_preserve_requests_and_reply_without_pause(agent,limit_kind):
    values={'max_steps':1} if limit_kind=='step' else {'max_read_units':1} if limit_kind=='cost' else {'max_seconds':.001,'clock':iter([0,1,2,3,4]).__next__}
    text='Give prices and financing'
    _,outcome=run(agent,text,understanding(text,'pricing','financing'),**values)
    assert outcome.stop_reason in {'step_limit','time_limit','read_cost_limit'}
    assert len(outcome.plan['request_coverage'])==2 and not agent.conversation.is_paused
    assert outcome.plan['external_actions']==0 and outcome.plan['additional_model_calls']==0


def test_tool_failure_stops_without_repeating_or_losing_task(agent):
    with patch.object(ReadTools,'execute',side_effect=RuntimeError('OFFLINE')) as lookup:
        _,outcome=run(agent,'Explain financing',understanding('Explain financing','financing'))
    assert lookup.call_count==1 and outcome.stop_reason=='no_new_information'
    assert outcome.state.tasks[-1].status=='suspended'


def test_read_feedback_unlocks_dependencies_in_later_round(agent):
    # Existing pending needs retain their dependency edges; no writes are added.
    agent.project.profile.profile_data={'payment_methods':['Bank financing'],'amenities':['Pool']}
    agent.project.profile.field_states={k:{'status':'confirmed','applicable':True} for k in ('payment_methods','amenities')};agent.db.commit()
    state=DialogueState(tasks=[Task(id='old-finance',topic='financing',status='pending'),Task(id='old-amenities',topic='amenities',status='pending',depends_on=['old-finance'])])
    save(agent.db,agent.scope,event_key='seed',expected_revision=0,state=state);agent.db.commit()
    _,outcome=run(agent,'Give me information',understanding('Give me information','catalog'))
    assert any(t.id=='old-amenities' and t.status=='completed' for t in outcome.state.tasks)
    assert len(outcome.plan['rounds'])>=2


def test_fresh_approved_information_reconsiders_blocked_read_but_greeting_does_not(agent):
    run(agent,'Explain financing',understanding('Explain financing','financing'))
    agent.project.profile.profile_data={'payment_methods':['Bank financing']};agent.project.profile.field_states={'payment_methods':{'status':'confirmed','applicable':True}};agent.db.commit()
    _,hello=run(agent,'Hello',understanding('Hello','other'))
    assert not hello.results
    _,outcome=run(agent,'What amenities are there?',understanding('What amenities are there?','amenities'))
    assert any(r.data.get('value')==['Bank financing'] for r in outcome.results)


def test_plan_retry_reuses_result_and_rejects_changed_budget(agent):
    row,outcome=run(agent,'Explain financing',understanding('Explain financing','financing'))
    event='test:'+row.id
    with patch.object(ReadTools,'execute',side_effect=AssertionError('Duplicate lookup')):
        again=run_turn(agent.db,agent.scope,message_id=row.id,understanding=understanding(row.content,'financing'),expected_revision=0,event_key=event)
        assert again==outcome
    with pytest.raises(DialogueConflict):run_turn(agent.db,agent.scope,message_id=row.id,understanding=understanding(row.content,'financing'),expected_revision=0,event_key=event,max_steps=1)


def test_terminal_compaction_keeps_long_conversations_bounded(agent):
    state=DialogueState(tasks=[Task(id='done-'+str(i),topic='catalog',status='completed') for i in range(100)])
    save(agent.db,agent.scope,event_key='seed',expected_revision=0,state=state);agent.db.commit()
    _,outcome=run(agent,'Give me information',understanding('Give me information','catalog'))
    assert len(outcome.state.tasks)<=21 and len(outcome.plan['retired_tasks'])==80


def test_capacity_deferral_records_every_current_need(agent):
    state=DialogueState(tasks=[Task(id='pending-'+str(i),topic='location',status='awaiting_user',property_id=str(i)) for i in range(100)])
    save(agent.db,agent.scope,event_key='seed',expected_revision=0,state=state);agent.db.commit()
    _,outcome=run(agent,'Explain financing',understanding('Explain financing','financing'))
    assert outcome.stop_reason=='capacity_limit' and outcome.plan['deferred_requests'][0]['topic']=='financing'
    assert outcome.plan['request_coverage']==[{'request_id':'r0','status':'capacity_deferred'}]
    assert 'financing' in outcome.plan['pending_topics']


def availability(agent):
    from app.modules.users.models import User,UserRole
    from app.modules.project_team.models import ProjectUserAssignment
    from app.modules.sales_crm.models import SalesAvailabilityBlock
    user=User(company_id=agent.company.id,email='sales@example.invalid',hashed_password='OFFLINE',role=UserRole.SALES,is_active=True,first_name='Test',last_name='Specialist')
    agent.db.add(user);agent.db.flush()
    agent.db.add(ProjectUserAssignment(project_id=agent.project.id,user_id=user.id,responsibility='sales',sales_enabled=True,accepts_appointments=True,is_active=True,accepts_new_leads=True))
    starts=(datetime.utcnow()+timedelta(days=2)).replace(hour=15,minute=0,second=0,microsecond=0)
    agent.db.add(SalesAvailabilityBlock(user_id=user.id,starts_at=starts,ends_at=starts+timedelta(hours=2),timezone='UTC'));agent.db.commit()
    return starts


def test_agenda_can_be_interrupted_by_plans_and_resumed_before_explicit_slot_confirmation(agent):
    starts=availability(agent)
    approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['floor_plan'])
    text='I want to arrange a visit'
    agent.turn(text,understanding(text,'appointment'))
    original_offer=load(agent.db,agent.scope)[1].offers
    text='Send plans first'
    agent.turn(text,understanding(text,'materials',subjects={0:'floor_plan'}))
    assert agent.db.query(SalesAssetShare).count()==1 and not agent.db.query(Meeting).count()
    text='I want to return to arranging a visit'
    agent.turn(text,understanding(text,'appointment'))
    assert not agent.db.query(Meeting).count()
    text='3:00 PM'
    agent.turn(text,typed(text,[req('slot','appointment',text,ref='slot')],[ref('slot','appointment',text)]))
    assert not agent.db.query(Meeting).count()
    agent.turn('Yes',understanding('Yes','other'))
    assert agent.db.query(Meeting).one().meeting_time==starts


def test_unit_materials_do_not_claim_specific_unit_coverage(agent):
    p=product(agent,'Studio')
    unit=ProjectUnit(project=agent.project,unit_code='A-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow())
    agent.db.add(unit);agent.db.commit()
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['brochure']);asset.property_type_id=p.id;agent.db.commit()
    text='Send the brochure for A-101'
    agent.turn(text,typed(text,[req('file','materials',text,ref='u',subject='brochure')],[ref('u','unit','A-101')]))
    assert not agent.db.query(SalesAssetShare).count() and 'specific unit is not confirmed' in agent.reply()


def test_property_pivot_clears_selected_unit_without_changing_preferences(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    unit=ProjectUnit(project=agent.project,unit_code='A-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow());agent.db.add(unit);agent.db.commit()
    revision,state=load(agent.db,agent.scope);state.selected_property_type_id=a.id;state.selected_unit_id=unit.id
    save(agent.db,agent.scope,event_key='unit',expected_revision=revision,state=state);agent.db.commit()
    agent.lead.meta_form_data={'budget':'200000 USD'};agent.db.commit()
    agent.turn('Loft',typed('Loft',[req('choice','property_details','Loft',ref='p')],[ref('p','property','Loft')]))
    state=load(agent.db,agent.scope)[1]
    assert state.selected_property_type_id==b.id and state.selected_unit_id is None
    assert agent.lead.meta_form_data['budget']=='200000 USD'


def test_repeated_prohibition_is_deduplicated_and_survives_other_topic(agent):
    for _ in range(3):run(agent,'No visit yet; explain financing',understanding('No visit yet; explain financing','financing'))
    state=load(agent.db,agent.scope)[1]
    assert len([c for c in state.constraints if c.topic.value=='appointment'])==1
    _,outcome=run(agent,'Send a brochure',understanding('Send a brochure','materials',subjects={0:'brochure'}))
    assert any(c.topic.value=='appointment' for c in outcome.state.constraints)


def test_unknown_reference_links_are_rejected_before_any_tool_call():
    with pytest.raises(ValueError):typed('Send plans',[req('x','materials','Send plans',ref='missing',subject='floor_plan')])


def test_unlinked_multi_subject_request_asks_instead_of_using_last_mentioned_property(agent):
    product(agent,'Studio');product(agent,'Loft')
    text='Studio and Loft plans'
    _,outcome=run(agent,text,typed(text,[req('plans','materials',text,subject='floor_plan')],[ref('a','property','Studio'),ref('b','property','Loft')]))
    assert outcome.plan['questions'] and not outcome.results


def test_tool_target_cannot_override_planner_binding(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    state=DialogueState(tasks=[Task(id='bound',topic='property_details',status='pending',property_id=a.id,binding_status='resolved')])
    result=ReadTools(agent.db,agent.scope).execute(ToolCall(operation_id='bound',task_id='bound',topic='property_details',property_id=b.id),state)
    assert result.status=='denied'


def test_dependency_round_limit_does_not_claim_all_needs_completed(agent):
    state=DialogueState(tasks=[Task(id='a',topic='catalog',status='pending'),Task(id='b',topic='catalog',status='pending',depends_on=['a'])])
    p=product(agent)
    save(agent.db,agent.scope,event_key='seed',expected_revision=0,state=state);agent.db.commit()
    _,outcome=run(agent,'Explain financing',understanding('Explain financing','financing'),max_rounds=1)
    assert outcome.stop_reason=='round_limit' and any(t.id=='b' and t.status=='pending' for t in outcome.state.tasks)


def test_terminal_pruning_preserves_dependency_targets(agent):
    state=DialogueState(tasks=[Task(id='needed',topic='catalog',status='completed'),Task(id='waiting',topic='materials',status='awaiting_user',depends_on=['needed'])]+
        [Task(id='old-'+str(i),topic='catalog',status='completed') for i in range(98)])
    save(agent.db,agent.scope,event_key='seed',expected_revision=0,state=state);agent.db.commit()
    _,outcome=run(agent,'Give me information',understanding('Give me information','catalog'))
    assert {'needed','waiting'}<={t.id for t in outcome.state.tasks}


def test_unknown_unit_price_is_not_marked_answered_from_parent_starting_price(agent):
    p=product(agent,'Studio');p.starting_price=200000;p.currency='USD'
    unit=ProjectUnit(project=agent.project,unit_code='A-101',typology='Studio',status='available',inventory_updated_at=datetime.utcnow())
    agent.db.add(unit);agent.db.commit()
    text='What is the price for A-101?'
    _,outcome=run(agent,text,typed(text,[req('price','pricing',text,ref='u')],[ref('u','unit','A-101')]))
    assert outcome.state.tasks[-1].status=='blocked' and outcome.results[0].data['units'][0]['price'] is None


def test_live_cost_limit_has_a_useful_reply_without_side_effects(agent):
    agent.config.agent_ventas={**agent.config.agent_ventas,'runtime_config':{**agent.config.agent_ventas['runtime_config'],'max_read_units':1}};agent.db.commit()
    text='Send a brochure'
    _,run_result=agent.turn(text,understanding(text,'materials',subjects={0:'brochure'}))
    assert run_result.status=='completed' and 'Which would you like me to handle next?' in agent.reply()
    assert not agent.db.query(SalesAssetShare).count() and not agent.conversation.is_paused
    assert run_result.output_snapshot['metadata']['planning']['read_units']==0


def test_clarifying_a_negative_refines_its_property_scope_without_waiving_it(agent):
    a=product(agent,'Studio');b=product(agent,'Loft')
    asset=approved_asset((agent.db,agent.company,agent.project,agent.lead,agent.conversation),['gallery_image']);asset.property_type_id=a.id;agent.db.commit()
    text='No photos for the other one; explain financing'
    agent.turn(text,typed(text,[req('finance','financing',text)],[ref('p','property','the other one')],
        constraints=[dict(topic='materials',subject='photos',scope='until_explicit_change',evidence='No photos for the other one',reference_id='p')]))
    agent.turn('Loft',typed('Loft',[req('choice','property_details','Loft',ref='p')],[ref('p','property','Loft')]))
    constraint=load(agent.db,agent.scope)[1].property_constraints[0]
    assert constraint.binding_status=='resolved' and constraint.property_id==b.id
    text='Send Studio photos'
    agent.turn(text,typed(text,[req('photos','materials',text,ref='p',subject='photos')],[ref('p','property','Studio')]))
    assert agent.db.query(SalesAssetShare).one().sales_asset_id==asset.id


@pytest.mark.parametrize('index',range(6))
@pytest.mark.parametrize('channel',['sms','whatsapp'])
def test_real_catalog_information_and_mixed_needs_use_bounded_planner(index,channel,monkeypatch):
    from sales_ai_support.sandbox import Sandbox,InboundHarness,load_catalog
    catalog=load_catalog();sandbox=Sandbox(catalog)
    text='Give property information and financing; no visit yet'
    try:
        project_id=catalog['projects'][index]['project']['id']
        h=InboundHarness(sandbox,project_id,channel,monkeypatch,understanding(text,'catalog','financing'))
        monkeypatch.setattr(settings,'SALES_NEXT_FLOW_ENABLED',True);monkeypatch.setattr(settings,'SALES_NEXT_FLOW_PROJECT_IDS',project_id)
        _,run_result=h.turn(text)
        assert run_result.status=='completed' and not h.conversation.is_paused,run_result.output_snapshot
        plan=run_result.output_snapshot['metadata']['planning']
        assert plan['version']=='sales-turn-planner/1.0' and len(plan['request_coverage'])==2
        assert plan['tool_calls']<=8 and plan['read_units']<=12 and plan['external_actions']==0
        assert not h.db.query(Meeting).count() and not h.calendar.calls
    finally:sandbox.close()
