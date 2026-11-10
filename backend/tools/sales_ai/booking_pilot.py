"""Six bounded scripted buyers. No LLM buyer, no fixture-created reservation."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

CASES = ('all_projects', 'one_project', 'unassigned_with_slots',
         'no_eligible_sales', 'no_slots', 'alternative_slot')
BOOKING_CASES = {'all_projects', 'one_project', 'alternative_slot'}


def team(db, manifest, scenario, clock):
    """Reset only laboratory schedule/team rows between independent cases."""
    from app.modules.users.models import User, UserRole
    from app.modules.project_team.models import ProjectUserAssignment, ProjectRoutingState
    from app.modules.sales_crm.models import SalesAvailabilityBlock, CalendarConnection, Meeting
    from .synthetic_fixtures import identifier
    assert db.bind.dialect.name == 'sqlite'
    for model in (CalendarConnection, SalesAvailabilityBlock, ProjectRoutingState, ProjectUserAssignment):
        db.query(model).delete(synchronize_session=False)
    project = manifest['projects'][0]
    rows=[]
    for number, key in enumerate(('all', 'specific', 'none', 'inactive', 'no_appointments')):
        uid=identifier('booking-sales-'+scenario+'-'+key)
        user=db.get(User,uid)
        if user is None:
            user=User(id=uid,company_id=manifest['company_id'],first_name='Synthetic',last_name=key,
                email=scenario+'-'+key+'@sales.synthetic.invalid',hashed_password='DISABLED-NOT-A-LOGIN',
                role=UserRole.SALES,is_active=True,project_access_scope='all' if key=='all' else 'selected')
            db.add(user);db.flush()
        user.is_active=key!='inactive'
        assigned = key in {'inactive','no_appointments'} or (key=='all' and scenario in {'all_projects','alternative_slot','no_slots'}) or (key=='specific' and scenario=='one_project')
        from app.modules.users.project_access import sync_user_project_access
        sync_user_project_access(db,user=user,scope='all' if key=='all' and assigned else 'selected',
            project_ids=[project['id']] if assigned and key!='all' else [],allow_empty_selected=True,
            sales_enabled=True,accepts_appointments=key!='no_appointments',accepts_new_leads=True)
        if scenario not in {'no_slots','no_eligible_sales'}:
            for day in (2,3,4):
                start=(clock+timedelta(days=day)).replace(hour=15,minute=0,second=0,microsecond=0)
                db.add(SalesAvailabilityBlock(user_id=uid,starts_at=start,ends_at=start+timedelta(hours=3),timezone='UTC'))
        rows.append({'id':uid,'scope':key,'assigned':assigned,'active':user.is_active})
    db.commit()
    return rows


def next_message(reply, history, *, alternative=False):
    """Read only public seller text, never private offer IDs or database slots."""
    if re.search(r'please confirm your visit',reply,re.I):
        return 'Yes', 'confirm'
    options=re.findall(r'^\s*\d+\.\s*(\d{4}-\d{2}-\d{2} at [^\n]+)',reply,re.M)
    if options:
        if alternative and not any(item['action']=='reject_first' for item in history):
            if len(options)<2:return None,'no_alternative_offered'
            return 'The first time does not work for me. I would like the second appointment: '+options[1]+'.', 'reject_first'
        return 'I would like the first appointment: '+options[0]+'.', 'select'
    if re.search(r'budget',reply,re.I):return 'My budget is 900,000 USD and I plan to pay cash. I would like to arrange the visit.', 'budget'
    if re.search(r'location|address|where.*visit',reply,re.I):return 'I want to visit Bay Residence at the project address, 1 Synthetic Avenue.', 'location'
    return 'I would like to visit Bay Residence in person. Any available time in the next seven days works for me. Please offer the available times in the project timezone.', 'request'


async def evaluate_case(db, manifest, scenario, budget, max_turns):
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesConversation,SalesMessage,AgentRun,OutboundMessage
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
    from app.modules.project_team.service import eligible_appointment_assignments
    from .evaluation_checks import check, error_details, internal_process_narration
    project=manifest['projects'][0]
    clock=datetime.utcnow()
    roster=team(db,manifest,scenario,clock)
    eligible={a.user_id for a in eligible_appointment_assignments(db,project['id'])}
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Scripted '+scenario,
        phone='+1555010'+str(CASES.index(scenario)+1000),platform='evaluation',is_demo=True,is_test=True,
        consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=manifest['company_id'],project_id=project['id'],lead_id=lead.id,
        channel='simulation',provider='simulation',is_paused=False)
    db.add(conversation);db.commit()
    rows=[];checks=[];confirmed=False;selected=False;selected_start=None;stop='turn_limit';last=''
    booking=scenario in BOOKING_CASES
    for index in range(max_turns):
        if budget.calls>=budget.maximum:stop='call_budget';break
        if index==0:
            message='I am interested in Bay Residence at Harbor Gardens and would like to book an in-person visit. My budget is 900,000 USD, paying cash. Any time in the next seven days works; please use the project timezone.'
            action='request'
        elif not booking:
            message,action='Understood, thank you. I will keep an eye out for new availability. Please do not book anything or set up an alert now.','acknowledge_unavailable'
        else:message,action=next_message(last,rows,alternative=scenario=='alternative_slot')
        if not message:stop=action;break
        if sum(r.get('lead_message')==message for r in rows)>=2:
            stop='repeated_selection_without_progress';break
        if action=='confirm' and not selected:stop='confirmation_without_selection';break
        confirmed |= action=='confirm';selected |= action in {'select','reject_first'}
        if action in {'select','reject_first'}:
            match=re.search(r'(\d{4}-\d{2}-\d{2} at \d{2}:\d{2} [AP]M) \(([^,]+),',message)
            if match:
                selected_start=datetime.strptime(match[1],'%Y-%m-%d at %I:%M %p').replace(tzinfo=ZoneInfo(match[2])).astimezone(timezone.utc).replace(tzinfo=None)
        event_id='booking-pilot:'+scenario+':'+str(index)
        before_ids=[m.id for m in db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound')]
        try:
            await turn(db,company_id=manifest['company_id'],lead_id=lead.id,inbound_text=message,event_id=event_id,
                virtual_now=clock+timedelta(seconds=10*(index+1)))
            run=db.query(AgentRun).filter_by(event_id=event_id).one()
            receipts=db.query(SalesMessage).filter(SalesMessage.conversation_id==conversation.id,
                SalesMessage.direction=='outbound',~SalesMessage.id.in_(before_ids)).order_by(SalesMessage.created_at,SalesMessage.id).all()
            last='\n\n'.join(m.content for m in receipts)
            meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
            events=db.query(SalesDialogueEvent).filter_by(conversation_id=conversation.id,kind='understanding_preview').order_by(SalesDialogueEvent.revision).all()
            attempts=next(((event.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) for event in reversed(events)
                if (event.payload_json.get('metadata') or {}).get('inbound_message_id')==(run.input_snapshot or {}).get('message_id')),[])
            rows.append({'interpretation_attempts':attempts,'turn':index+1,'action':action,'lead_message':message,'reply':last,
                'understanding':(run.input_snapshot or {}).get('understanding'),'output':run.output_snapshot,
                'input_trace':run.input_snapshot,'error_code':run.error_code,
                'checks':[check('reply_present',bool(last.strip())),check('interpretation_accepted',not run.error_code),
                    check('no_internal_narration',not internal_process_narration(last)),
                    check('no_booking_before_confirmation',not meetings or confirmed),
                    check('selection_advances_to_confirmation',action not in {'select','reject_first'} or bool(re.search(r'Please confirm your visit',last,re.I))),
                    check('no_identical_consecutive_reply',not rows or last!=rows[-1].get('reply')),
                    check('no_invented_frustration',not ((run.input_snapshot or {}).get('understanding') or {}).get('empathy') if action=='acknowledge_unavailable' else True),
                    check('no_duplicate_booking',len(meetings)<=1)]})
            if meetings:
                stop='booked';break
            if not booking and index>=1:
                stop='unavailable_dialogue_observed';break
        except Exception as exc:
            db.rollback();rows.append({'turn':index+1,'action':action,'lead_message':message,**error_details(exc),'checks':[check('engine_turn_completed',False)]})
            stop='engine_error';break
    meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
    checks += [check('no_provider_outbox',db.query(OutboundMessage).count()==0),
        check('expected_booking_outcome',len(meetings)==(1 if booking else 0)),
        check('confirmed_only_after_explicit_selection',not meetings or (confirmed and selected))]
    if booking and meetings:
        meeting=meetings[0]
        checks += [check('eligible_sales_assigned',meeting.assigned_sales_user_id in eligible),
            check('correct_project_and_lead',meeting.project_id==project['id'] and meeting.lead_id==lead.id),
            check('location_recorded',bool(meeting.visit_address)),
            check('booked_time_matches_public_selection',selected_start is not None and meeting.meeting_time==selected_start),
            check('public_confirmation_matches_booking',bool(re.search(r'your visit is confirmed',last,re.I))),
            check('confirmed_status',meeting.confirmation_status=='confirmed')]
        # Replay exactly the same inbound event: no second reservation or model call.
        calls=budget.calls
        await turn(db,company_id=manifest['company_id'],lead_id=lead.id,inbound_text=message,event_id=event_id)
        checks += [check('duplicate_event_is_idempotent',db.query(Meeting).filter_by(lead_id=lead.id).count()==1 and budget.calls==calls)]
    if not booking:
        checks += [check('unavailability_explained',bool(re.search(r'no .*(?:available|times|slots)|not available|no availability|could not find a verified time|unable|cannot.*(?:visit|schedule)',' '.join(r.get('reply','') for r in rows),re.I))),
            check('no_visit_options_offered',not any(re.search(r'Verified visit options',r.get('reply','')) for r in rows))]
        checks.append({'check':'appropriate_future_availability_wording','status':'BLOCKED','detail':'Human review required; no future notification automation is created.'})
    if scenario=='alternative_slot':checks.append(check('alternative_chosen',any(r['action']=='reject_first' for r in rows)))
    return {'case':scenario,'project_id':project['id'],'clock_utc':clock.isoformat(),'team':roster,
        'eligible_sales_ids':sorted(eligible),'stop_reason':stop,'turns':rows,'checks':checks,
        'meetings':[{'id':m.id,'project_id':m.project_id,'lead_id':m.lead_id,'sales_user_id':m.assigned_sales_user_id,
            'starts_at_utc':m.meeting_time.isoformat(),'duration_minutes':m.duration_minutes,
            'address':m.visit_address,'calendar_sync_status':m.calendar_sync_status} for m in meetings]}
