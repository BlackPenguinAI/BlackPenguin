"""Multi-turn scripted continuity experiments. No buyer LLM or live contacts.

Development and transfer variants are reported separately, never pooled into a
claim of integral dialogue quality. Backend metadata drives selection, not guessed
availability. Every booking still needs a public summary and final confirmation.
"""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

VERSION='sales-continuity-battery/1.2'
SPECS={
 'development_bay':{'split':'development','project':0,'property':0,'access':'all','material':'photos','date_style':'day_month','visit':'I want to visit {name}'},
 'development_cedar':{'split':'development','project':1,'property':0,'access':'selected','material':'photos','date_style':'numeric','visit':'I would like to visit {name}'},
 'development_missing':{'split':'development','project':2,'property':0,'access':'all','material':'photos','date_style':'month_day','visit':'Please schedule a visit to {name}'},
 'transfer_bay':{'split':'transfer','project':0,'property':0,'access':'selected','material':'floor_plan','date_style':'month_day','visit':'Could I arrange a viewing of {name}?'},
 'transfer_cedar':{'compare_switch':True,'split':'transfer','project':1,'property':1,'access':'all','material':'floor_plan','date_style':'day_month','visit':"I'd like to book a visit to {name}."},
 'transfer_no_sellers':{'split':'transfer','project':2,'property':0,'access':'unassigned','material':'floor_plan','date_style':'numeric','visit':'Can we schedule a visit to {name}?'},
}
for key,base,phrase in [
    ('resume_missing_visit','development_missing','Visit?'),
    ('resume_cedar_viewing','development_cedar','A viewing?'),
    ('resume_bay_see','transfer_bay','Can I visit the property?'),
]:
    SPECS[key]={**SPECS[base],'split':'resumption','resume':True,'visit':phrase}
SPECS['context_material_see']={**SPECS['resume_bay_see'],'split':'contextual','material_acceptance':True}
SPECS['context_visit_see']={**SPECS['resume_bay_see'],'split':'contextual','visit_invitation_context':True,'visit':'Can I see it?'}
CASES=tuple(SPECS)

async def evaluate_case(db,manifest,key,budget,max_turns):
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesConversation,SalesMessage,AgentRun,OutboundMessage
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.dialogue_store import Scope,load
    from .evaluation_checks import check,internal_process_narration
    from . import compact_battery as compact
    from .booking_pilot import explains_unavailability
    from copy import deepcopy
    spec=SPECS[key];project=manifest['projects'][spec['project']];prop=project['properties'][spec['property']];clock=datetime.utcnow()
    # Reuse established synthetic sales memberships/availability; restore registry.
    original=compact.SPECS.get(key)
    compact.SPECS[key]={**deepcopy(compact.SPECS['first_time_A']),**spec}
    try:roster=compact.team(db,manifest,key,clock)
    finally:
        if original is None:del compact.SPECS[key]
        else:compact.SPECS[key]=original
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Fictional continuity '+key,phone='+1555060'+str(1000+CASES.index(key) if key in CASES else 2000+int(__import__('hashlib').sha256(key.encode()).hexdigest()[:5],16)%8000),platform='evaluation',is_demo=True,is_test=True,consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.flush();conversation=SalesConversation(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False);db.add(conversation);db.commit()
    if spec.get('ordinal'):
        from app.modules.sales_crm.models import SalesAvailabilityBlock
        for block in db.query(SalesAvailabilityBlock).all():
            block.starts_at+=timedelta(hours=10 if spec.get('period_variant')=='evening' else 4);block.ends_at+=timedelta(hours=10 if spec.get('period_variant')=='evening' else 4)
        db.commit()
    first=project['properties'][0] if spec.get('compare_switch') else prop
    initial=[('discover',f"I am looking for a {first['bedrooms']} bedroom home."),('choose',first['name']),('material','Do you have photos of the property?' if spec['material']=='photos' else 'Show me the property blueprints'),('visit',spec['visit'].format(name=prop['name']))]
    if spec.get('compare_switch'):
        initial[2:2]=[('compare','How does this property differ from the others?'),('switch',f"Actually I prefer {prop['name']} instead.")]
    if spec.get('resume'):
        from app.modules.sales_agent.dialogue_store import save
        from app.modules.sales_agent.understanding_contract import DialogueState,Task
        old=next((p for p in project['properties'] if p['id']!=prop['id']),prop)
        state=DialogueState(selected_property_type_id=old['id'],tasks=[Task(
            id='old-unresolved-visit',topic='appointment',status='awaiting_user',
            property_id=old['id'],binding_status='unresolved',blocked_reason='reference_clarification')],
            booking_search={'property_type_id':old['id'],'timezone':'America/Chicago'})
        save(db,Scope(lead.company_id,lead.project_id,conversation.id,lead.id),event_key='synthetic-prior-session',expected_revision=0,state=state)
        db.commit()
        initial.insert(0,('greeting','Hi'))
        index=next(i for i,(action,_) in enumerate(initial) if action=='material')
        initial.insert(index+1,('material_repeat','I want to check blueprints' if spec['material']=='floor_plan' else 'Can you show me pictures?'))
    if spec.get('material_acceptance'):
        index=next(i for i,(action,_) in enumerate(initial) if action=='visit')
        initial.insert(index,('accept_material','Can I see it?'))
    if spec.get('visit_invitation_context'):
        initial=[row for row in initial if row[0] not in {'material','material_repeat'}]
    if spec.get('dialogue'):
        initial=[(a,t.format(name=prop['name'],first=first['name'])) for a,t in spec['dialogue']]
    post=list(spec.get('post_booking') or []);post_index=0
    if spec.get('unknown_financing'):
        from app.modules.projects.models import Project
        owner=db.get(Project,project['id']);data=deepcopy(owner.profile.profile_data or {})
        for field in ('payment_methods','financing','financing_options','payment_options'):data.pop(field,None)
        owner.profile.profile_data=data
        published=deepcopy(owner.profile.published_snapshot or {})
        for container in ('data','profile_data','facts'):
            if isinstance(published.get(container),dict):
                for field in ('payment_methods','financing','financing_options','payment_options'):published[container].pop(field,None)
        owner.profile.published_snapshot=published;db.commit()
    if spec.get('long_history'):
        for n in range(80):
            db.add(SalesMessage(conversation_id=conversation.id,channel='simulation',direction='inbound' if n%2==0 else 'outbound',role='user' if n%2==0 else 'assistant',content='Earlier I was exploring another option.' if n%2==0 else 'I could not complete that request. Please try again.',status='received' if n%2==0 else 'delivered',metadata_json={'synthetic_context_seed':True},created_at=clock-timedelta(minutes=90-n)))
        db.commit()
    rows=[];latest_meta={};selected=False;confirmed=False;stop='turn_limit';expected_start=None
    try:
        for i in range(max_turns):
            if budget.calls>=budget.maximum:stop='call_budget';break
            if i<len(initial):action,message=initial[i]
            elif confirmed and post_index<len(post):
                action,message=post[post_index];post_index+=1
            elif spec.get('goal')=='discussion':stop='script_completed';break
            elif (spec.get('visit_invitation_context') and rows[-1]['action']=='visit'
                  and not latest_meta.get('appointment_offer') and '?' in rows[-1]['reply']
                  and any(w in rows[-1]['reply'].lower() for w in ('visit','viewing','in person'))):
                action,message='visit_clarified',f"I mean an in-person visit to {prop['name']}."
            elif (rows[-1]['action'] in {'visit','visit_clarified'} and
                  rows[-1]['reply'].startswith('Would you like me to check available visit times for ') and not latest_meta.get('appointment_offer')):
                action,message='visit_search_accepted',f"Yes, please check available visit times for {prop['name']}."
            elif latest_meta.get('booking_confirmation'):
                action,message='confirm','Yes';confirmed=True
            elif latest_meta.get('appointment_offer'):
                offer=latest_meta['appointment_offer'];option=offer['options'][2 if spec.get('ordinal') and len(offer['options'])>=3 else 0];expected_start=option['starts_at']
                local=datetime.fromisoformat(expected_start).astimezone(ZoneInfo(offer['preferences']['timezone']))
                date=local.strftime('%d %B') if spec['date_style']=='day_month' else local.strftime('%d/%m') if spec['date_style']=='numeric' else local.strftime('%B %d')
                action,message='select',('Option 3' if spec.get('ordinal') and len(offer['options'])>=3 else date+', '+local.strftime('%I:%M%p').lstrip('0'));selected=True
            else:stop='missing_public_next_step';break
            if spec.get('visit_invitation_context') and action=='visit':
                # Explicitly declared prior assistant context in this synthetic case.
                # This seeds an invitation, not availability, a proposal or consent.
                invitation=SalesMessage(conversation_id=conversation.id,channel='simulation',direction='outbound',role='assistant',
                    content=f"Would you like to review in-person visit options for {prop['name']}?",
                    status='delivered',metadata_json={'visit_invitation':True,'synthetic_context_seed':True},
                    created_at=clock+timedelta(seconds=i*10-1))
                db.add(invitation);db.commit()
            previous_meta=latest_meta
            before={m.id for m in db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound')}
            event=f'continuity:{key}:{i}'
            from time import monotonic
            started=monotonic()
            await turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=message,event_id=event,virtual_now=clock+timedelta(seconds=i*10))
            run=db.query(AgentRun).filter_by(event_id=event).one();meta=(run.output_snapshot or {}).get('metadata') or {};latest_meta=meta
            reply='\n\n'.join(m.content for m in db.query(SalesMessage).filter(SalesMessage.conversation_id==conversation.id,SalesMessage.direction=='outbound',~SalesMessage.id.in_(before)).order_by(SalesMessage.created_at,SalesMessage.id))
            revision,state=load(db,Scope(lead.company_id,lead.project_id,conversation.id,lead.id));meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
            checks=[check('turn_completed',not run.error_code),check('reply_present',bool(reply)),check('english_reply_not_rejected',not meta.get('language_hold')),check('no_internal_narration',not internal_process_narration(reply) and 'in this query' not in reply.lower() and 'approved, accessible' not in reply.lower() and not any(marker in reply.lower() for marker in ('synthetic property for testing','only the listed features are confirmed','isolated sales-agent evaluation'))),check('no_booking_before_selection_and_final_confirmation',not meetings or selected and confirmed)]
            if action in {'choose','compare','switch','material','visit','select','confirm','material_repeat','accept_material','visit_clarified','visit_search_accepted'}:
                expected_property=first['id'] if action in {'choose','compare'} else prop['id']
                checks.append(check('active_property_retained',state.selected_property_type_id==expected_property))
            if action=='choose':
                checks.append(check('named_choice_answers_details_without_business_requestion',
                    first['name'] in reply and not (run.input_snapshot or {}).get('understanding',{}).get('requires_clarification') and
                    not any(w in reply.lower() for w in ('clarify whether','which property','what would you like to know?'))))
            if action=='compare':checks.append(check('comparison_has_both_properties',all(p['name'] in reply for p in project['properties'])))
            if action in {'material','material_repeat'}:checks.extend([check('no_property_requestion','which property' not in reply.lower()),check('material_not_comparison','make this comparison' not in reply.lower())])
            if action in {'material','material_repeat'} and spec['material']=='photos':
                has_gallery=any(r['kind']=='gallery' for r in prop['resources'])
                checks.append(check('requested_photos_or_truthful_absence',('http' in reply) if has_gallery else not 'http' in reply and ('not' in reply.lower() or "don't" in reply.lower())))
            if spec.get('resume'):
                checks.append(check('no_stale_visit_refrain',"we can return to arranging your visit" not in reply.lower()))
                checks.append(check('saved_search_matches_current_property',not state.booking_search or state.booking_search.get('property_type_id')==state.selected_property_type_id))
                if action in {'material','material_repeat'}:
                    checks.append(check('material_question_answered',bool(meta.get('material_offer')) or 'http' in reply or any(word in reply.lower() for word in ["don't have",'not available','not confirm','not verify'])))
            if action=='greeting':
                checks.append(check('greeting_without_business_clarification',not (run.input_snapshot or {}).get('understanding',{}).get('requires_clarification') and 'clarify whether' not in reply.lower()))
            if action=='material_repeat' and not meta.get('material_bindings'):
                checks.append(check('repeated_gap_acknowledged',reply!=rows[-1]['reply'] and 'still' in reply.lower()))
            if action=='accept_material':
                bindings=meta.get('material_bindings') or []
                allowed=set((previous_meta.get('material_offer') or {}).get('asset_ids') or [])
                received={b['binding']['asset_id'] for b in bindings}
                targeted_question='?' in reply and any(word in reply.lower() for word in ('file','gallery','brochure','material'))
                checks.extend([check('file_acceptance_not_visit',not meetings and not meta.get('appointment_offer')),
                    check('offered_material_or_focused_clarification',bool(received) and received<=allowed or targeted_question)])
            if action in {'visit','visit_clarified','visit_search_accepted'}:
                focused_clarification=bool(spec.get('visit_invitation_context') and action=='visit' and '?' in reply and
                    any(w in reply.lower() for w in ('visit','viewing','in person')) and not any(w in reply.lower() for w in ('financing','budget')))
                search_question=bool((run.input_snapshot or {}).get('focused_visit_clarification') and
                    reply.startswith('Would you like me to check available visit times for ') and reply.rstrip().endswith('?') and
                    not meta.get('appointment_offer') and not meta.get('meeting_id') and not meetings)
                checks.append(check('visit_reaches_options_or_unavailability',bool(meta.get('appointment_offer')) or explains_unavailability(reply) or focused_clarification or search_question))
                if (run.input_snapshot or {}).get('focused_visit_clarification'):
                    checks.append(check('focused_search_question_has_no_effects',search_question))
            if action=='select':checks.append(check('selection_prepares_summary',bool(meta.get('booking_confirmation')) and not meetings))
            if action=='confirm':checks.append(check('confirmation_books_current_summary',len(meetings)==1 and bool(meta.get('meeting_id'))))
            from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
            trace=db.query(SalesDialogueEvent).filter_by(conversation_id=conversation.id,event_key='active-understanding:'+str((run.input_snapshot or {}).get('message_id'))).first()
            attempts=(trace.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) if trace else []
            rows.append({'booking_confirmation_authorization':(run.input_snapshot or {}).get('booking_confirmation_authorization'),'observation_loop':(run.input_snapshot or {}).get('observation_loop'),'runtime_error':run.error_code,'error_diagnostic':(run.output_snapshot or {}).get('error_diagnostic'),'coordinator_graph':(run.input_snapshot or {}).get('coordinator_graph'),'bounded_reconsideration':(run.input_snapshot or {}).get('bounded_reconsideration'),'elapsed_ms':round((monotonic()-started)*1000),'interpretation_attempts':attempts,'read_authorization':(run.input_snapshot or {}).get('dialogue_read_authorization'),'focused_visit_clarification':(run.input_snapshot or {}).get('focused_visit_clarification'),'lead_projection':{'intent_score':lead.intent_score,'intent_tier':lead.intent_tier,'segment':lead.assigned_segment,'next_action_at':str(lead.next_action_at) if lead.next_action_at else None,'cadence_stop_reason':state.cadence_stop_reason},'meeting_ids':[m.id for m in meetings],'turn':i+1,'action':action,'lead_message':message,'reply':reply,'understanding':(run.input_snapshot or {}).get('understanding'),'metadata':meta,'checks':checks})
            if meetings and (not post or post_index>=len(post)):stop='booked';break
            if spec['access']=='unassigned' and action=='visit':stop='unavailable';break
    except Exception as exc:
        exc.sales_partial_case={'case':key,'turns':rows,'checks':[check('case_completed',False)]}
        raise
    meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
    final=[check('goal_reached',stop==('script_completed' if spec.get('goal')=='discussion' else 'unavailable' if spec['access']=='unassigned' else 'booked')),check('at_most_one_booking',len(meetings)<=1),check('no_live_outbox',db.query(OutboundMessage).count()==0)]
    if meetings:
        final.extend([check('correct_property_booked',meetings[0].visit_property_type_id==prop['id']),check('time_matches_selected_offer',meetings[0].meeting_time==datetime.fromisoformat(expected_start).replace(tzinfo=None))])
    return {'case':key,'script_version':VERSION,'context_seed':'explicit_visit_invitation' if spec.get('visit_invitation_context') else 'prior_unresolved_appointment' if spec.get('resume') else 'fresh','split':spec['split'],'lead_id':lead.id,'conversation_id':conversation.id,'turns':rows,'stop_reason':stop,'checks':final,'meetings':[{'id':m.id,'time':m.meeting_time,'property_id':m.visit_property_type_id} for m in meetings],'overall_dialogue_quality':'NOT_EVALUATED'}
