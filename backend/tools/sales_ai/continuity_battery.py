"""Multi-turn scripted continuity experiments. No buyer LLM or live contacts.

Development and transfer variants are reported separately, never pooled into a
claim of integral dialogue quality. Backend metadata drives selection, not guessed
availability. Every booking still needs a public summary and final confirmation.
"""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

VERSION='sales-continuity-battery/1.0'
SPECS={
 'development_bay':{'split':'development','project':0,'property':0,'access':'all','material':'photos','date_style':'day_month','visit':'I want to visit {name}'},
 'development_cedar':{'split':'development','project':1,'property':0,'access':'selected','material':'photos','date_style':'numeric','visit':'I would like to visit {name}'},
 'development_missing':{'split':'development','project':2,'property':0,'access':'all','material':'photos','date_style':'month_day','visit':'Please schedule a visit to {name}'},
 'transfer_bay':{'split':'transfer','project':0,'property':0,'access':'selected','material':'floor_plan','date_style':'month_day','visit':'Could I arrange a viewing of {name}?'},
 'transfer_cedar':{'compare_switch':True,'split':'transfer','project':1,'property':1,'access':'all','material':'floor_plan','date_style':'day_month','visit':"I'd like to book a visit to {name}."},
 'transfer_no_sellers':{'split':'transfer','project':2,'property':0,'access':'unassigned','material':'floor_plan','date_style':'numeric','visit':'Can we schedule a visit to {name}?'},
}
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
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Fictional continuity '+key,phone='+1555060'+str(1000+CASES.index(key)),platform='evaluation',is_demo=True,is_test=True,consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.flush();conversation=SalesConversation(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False);db.add(conversation);db.commit()
    first=project['properties'][0] if spec.get('compare_switch') else prop
    initial=[('discover',f"I am looking for a {first['bedrooms']} bedroom home."),('choose',first['name']),('material','Do you have photos of the property?' if spec['material']=='photos' else 'Show me the property blueprints'),('visit',spec['visit'].format(name=prop['name']))]
    if spec.get('compare_switch'):
        initial[2:2]=[('compare','How does this property differ from the others?'),('switch',f"Actually I prefer {prop['name']} instead.")]
    rows=[];latest_meta={};selected=False;confirmed=False;stop='turn_limit';expected_start=None
    for i in range(max_turns):
        if budget.calls>=budget.maximum:stop='call_budget';break
        if i<len(initial):action,message=initial[i]
        elif latest_meta.get('booking_confirmation'):
            action,message='confirm','Yes';confirmed=True
        elif latest_meta.get('appointment_offer'):
            offer=latest_meta['appointment_offer'];option=offer['options'][0];expected_start=option['starts_at']
            local=datetime.fromisoformat(expected_start).astimezone(ZoneInfo(offer['preferences']['timezone']))
            date=local.strftime('%d %B') if spec['date_style']=='day_month' else local.strftime('%d/%m') if spec['date_style']=='numeric' else local.strftime('%B %d')
            action,message='select',date+', '+local.strftime('%I:%M%p').lstrip('0');selected=True
        else:stop='missing_public_next_step';break
        before={m.id for m in db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound')}
        event=f'continuity:{key}:{i}'
        await turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=message,event_id=event,virtual_now=clock+timedelta(seconds=i*10))
        run=db.query(AgentRun).filter_by(event_id=event).one();meta=(run.output_snapshot or {}).get('metadata') or {};latest_meta=meta
        reply='\n\n'.join(m.content for m in db.query(SalesMessage).filter(SalesMessage.conversation_id==conversation.id,SalesMessage.direction=='outbound',~SalesMessage.id.in_(before)).order_by(SalesMessage.created_at,SalesMessage.id))
        revision,state=load(db,Scope(lead.company_id,lead.project_id,conversation.id,lead.id));meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
        checks=[check('turn_completed',not run.error_code),check('reply_present',bool(reply)),check('english_reply_not_rejected',not meta.get('language_hold')),check('no_internal_narration',not internal_process_narration(reply) and 'in this query' not in reply.lower() and 'approved, accessible' not in reply.lower()),check('no_booking_before_selection_and_final_confirmation',not meetings or selected and confirmed)]
        if action in {'choose','compare','switch','material','visit','select','confirm'}:
            expected_property=first['id'] if action in {'choose','compare'} else prop['id']
            checks.append(check('active_property_retained',state.selected_property_type_id==expected_property))
        if action=='compare':checks.append(check('comparison_has_both_properties',all(p['name'] in reply for p in project['properties'])))
        if action=='material':checks.extend([check('no_property_requestion','which property' not in reply.lower()),check('material_not_comparison','make this comparison' not in reply.lower())])
        if action=='material' and spec['material']=='photos':
            has_gallery=any(r['kind']=='gallery' for r in prop['resources'])
            checks.append(check('requested_photos_or_truthful_absence',('http' in reply) if has_gallery else not 'http' in reply and ('not' in reply.lower() or "don't" in reply.lower())))
        if action=='visit':checks.append(check('visit_reaches_options_or_unavailability',bool(meta.get('appointment_offer')) or explains_unavailability(reply)))
        if action=='select':checks.append(check('selection_prepares_summary',bool(meta.get('booking_confirmation')) and not meetings))
        if action=='confirm':checks.append(check('confirmation_books_current_summary',len(meetings)==1 and bool(meta.get('meeting_id'))))
        from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
        trace=db.query(SalesDialogueEvent).filter_by(conversation_id=conversation.id,event_key='active-understanding:'+str((run.input_snapshot or {}).get('message_id'))).first()
        attempts=(trace.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) if trace else []
        rows.append({'interpretation_attempts':attempts,'read_authorization':(run.input_snapshot or {}).get('dialogue_read_authorization'),'turn':i+1,'action':action,'lead_message':message,'reply':reply,'understanding':(run.input_snapshot or {}).get('understanding'),'metadata':meta,'checks':checks})
        if meetings:stop='booked';break
        if spec['access']=='unassigned' and action=='visit':stop='unavailable';break
    meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
    final=[check('goal_reached',stop==('unavailable' if spec['access']=='unassigned' else 'booked')),check('at_most_one_booking',len(meetings)<=1),check('no_live_outbox',db.query(OutboundMessage).count()==0)]
    if meetings:
        final.extend([check('correct_property_booked',meetings[0].visit_property_type_id==prop['id']),check('time_matches_selected_offer',meetings[0].meeting_time==datetime.fromisoformat(expected_start).replace(tzinfo=None))])
    return {'case':key,'split':spec['split'],'lead_id':lead.id,'conversation_id':conversation.id,'turns':rows,'stop_reason':stop,'checks':final,'meetings':[{'id':m.id,'time':m.meeting_time,'property_id':m.visit_property_type_id} for m in meetings],'overall_dialogue_quality':'NOT_EVALUATED'}
