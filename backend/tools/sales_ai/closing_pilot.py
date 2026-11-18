"""Eight short dialogues for contact requests and respectful closing behavior."""
from .commercial_pilot import evaluate_case as evaluate_commercial,FAREWELL

SCENARIOS={
 'decline_visit_questions':(0,["I do not want a visit yet. What financing options do you offer?",FAREWELL],'none'),
 'human_then_question':(0,['I want to speak to a human','What financing options do you offer?',FAREWELL],'none'),
 'human_insists':(0,['I want to speak to a human','I still want to speak to a human'],'none'),
 # Finance must be answered before the explicitly confirmed pause.
 'human_record_then_question':(0,['I want to speak to a human','What financing options do you offer?','I still want to speak to a human'],'none'),
 # Withdrawal of an unconfirmed request leaves the AI active.
 'human_withdrawal':(0,['I want to speak to a human','I no longer need a human',FAREWELL],'none'),
 'farewell_then_reopen':(0,[FAREWELL,'What financing options do you offer?',FAREWELL],'none'),
 'unavailable_then_close':(0,['I would like to book an in-person visit to Bay Residence at Harbor Gardens. My budget is 900,000 USD, paying cash. Any time in the next seven days works; please use the project timezone.','Understood, thank you. Please do not book anything or set up an alert now.',FAREWELL],'none'),
 'mixed_human_price':(0,['I want to speak to a human. What is the price of Bay Residence?','I still want to speak to a human'],'none'),
}
CASES=tuple(SCENARIOS)


def extra_checks(db,lead,row,index,scenario):
    import re
    from app.modules.governance.models import HumanInterventionCase,NotificationOutbox
    from app.modules.sales_agent.models import SalesConversation,SalesFollowUpJob
    from app.modules.sales_agent.conversation_review import review_snapshot
    from .evaluation_checks import check
    conversation=db.query(SalesConversation).filter_by(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation').one()
    cases=db.query(HumanInterventionCase).filter_by(company_id=lead.company_id,project_id=lead.project_id,conversation_id=conversation.id,lead_id=lead.id,reason='HUMAN_REQUESTED').all()
    expected=(scenario in {'human_insists','mixed_human_price'} and index==1 or
              scenario=='human_record_then_question' and index==2)
    checks=[check('contact_request_count_matches_consent',len(cases)==int(expected)),
        check('human_control_matches_confirmed_request',conversation.is_paused==expected and
              (lead.agent_status=='human_control')==expected and not lead.is_opt_out),
        check('no_callback_or_transfer_promise',not re.search(r'will (?:call|contact)|within \d|have (?:transferred|connected) you',row['reply'],re.I))]
    if expected:
        visible=review_snapshot(db,conversation)['intervention_cases']
        checks.append(check('request_visible_to_staff',len(cases)==1 and any(c['id']==cases[0].id for c in visible)))
        checks.append(check('request_status',len(cases)==1 and cases[0].status=='open'))
        checks.append(check('administrator_review_notification_queued',
            db.query(NotificationOutbox).filter_by(company_id=lead.company_id,project_id=lead.project_id,
                entity_type='lead',entity_id=lead.id,event_type='human_intervention').count()==1))
        pending=db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').all()
        checks.append(check('no_marketing_or_inactivity_after_insistence',not any(j.kind=='inactivity' or j.reason.endswith('_cadence') for j in pending)))
    if scenario=='human_withdrawal' and index==1:
        checks.append(check('unconfirmed_request_withdrawn_without_pausing',
            ((row.get('output') or {}).get('metadata') or {}).get('human_contact_stage')=='withdraw'))
    if row['lead_message']==FAREWELL:checks.append(check('farewell_does_not_ask_another_question','?' not in row['reply']))
    if row['lead_message']=='What financing options do you offer?':checks.append(check('actual_question_answered','Bank financing' in row['reply']))
    if scenario=='mixed_human_price' and index==0:checks.append(check('mixed_price_answered','780,000.00 USD' in row['reply']))
    if scenario=='decline_visit_questions' and index==0:checks.append(check('decline_does_not_reinvite_visit','Would you like to review visit options' not in row['reply']))
    if scenario=='unavailable_then_close' and index==1:checks.append(check('unavailability_closure_invites_other_question','another property question' in row['reply']))
    # External reply checks alone hid missing financing reads in P1-C v3.
    # Verify actual read execution and no unfinished mandatory work.
    trace=row.get('input_trace') or {}
    loop=trace.get('observation_loop') or {}
    understanding=row.get('understanding') or {}
    if loop:
        checks.append(check('no_internal_observation_failure',loop.get('status')!='FAIL'))
    if 'What financing options do you offer?' in row['lead_message']:
        finance_reads=[tool for tool in loop.get('tools',[]) if
            (tool.get('arguments') or {}).get('topic')=='financing' and tool.get('status')=='success']
        checks.extend([
            check('financing_question_does_not_require_clarification',not understanding.get('requires_clarification')),
            check('financing_observation_completes',loop.get('status')=='PASS'),
            check('financing_was_read_from_approved_source',bool(finance_reads)),
            check('financing_has_no_unread_required_tasks',not loop.get('unread_required_tasks')),
            check('no_redundant_financing_clarification','Could you clarify whether' not in row['reply']),
        ])
    if scenario=='unavailable_then_close' and index==0:
        metadata=(row.get('output') or {}).get('metadata') or {}
        checks.extend([
            check('scoped_visit_does_not_require_reference_clarification',not metadata.get('reference_question')),
            check('scoped_visit_search_completes',loop.get('status')=='PASS'),
            check('scoped_visit_availability_was_checked',any(o.get('operation_id')=='visit_availability' for o in loop.get('observations',[]))),
        ])
    return checks


async def evaluate_case(db,manifest,scenario,budget,max_turns):
    return await evaluate_commercial(db,manifest,scenario,budget,max_turns,scenarios=SCENARIOS,extra_checks=extra_checks)
