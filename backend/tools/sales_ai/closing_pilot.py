"""Eight short dialogues for contact requests and respectful closing behavior."""
from .commercial_pilot import evaluate_case as evaluate_commercial,FAREWELL

SCENARIOS={
 'decline_visit_questions':(0,["I do not want a visit yet. What financing options do you offer?",FAREWELL],'none'),
 'human_then_question':(0,['I want to speak to a human','What financing options do you offer?',FAREWELL],'none'),
 'human_insists':(0,['I want to speak to a human','I still want to speak to a human',FAREWELL],'none'),
 'human_record_then_question':(0,['I want to speak to a human','I still want to speak to a human','What financing options do you offer?',FAREWELL],'none'),
 'human_withdrawal':(0,['I want to speak to a human','I still want to speak to a human','I no longer need a human',FAREWELL],'none'),
 'farewell_then_reopen':(0,[FAREWELL,'What financing options do you offer?',FAREWELL],'none'),
 'unavailable_then_close':(0,['I would like to book an in-person visit to Bay Residence at Harbor Gardens. My budget is 900,000 USD, paying cash. Any time in the next seven days works; please use the project timezone.','Understood, thank you. Please do not book anything or set up an alert now.',FAREWELL],'none'),
 'mixed_human_price':(0,['I want to speak to a human. What is the price of Bay Residence?','I still want to speak to a human',FAREWELL],'none'),
}
CASES=tuple(SCENARIOS)


def extra_checks(db,lead,row,index,scenario):
    import re
    from app.modules.governance.models import HumanInterventionCase
    from app.modules.sales_agent.models import SalesConversation,SalesFollowUpJob
    from app.modules.sales_agent.conversation_review import review_snapshot
    from .evaluation_checks import check
    conversation=db.query(SalesConversation).filter_by(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,channel='simulation').one()
    cases=db.query(HumanInterventionCase).filter_by(company_id=lead.company_id,project_id=lead.project_id,conversation_id=conversation.id,lead_id=lead.id,reason='HUMAN_CONTACT_REQUEST').all()
    expected=scenario in {'human_insists','human_record_then_question','human_withdrawal','mixed_human_price'} and index>=1
    checks=[check('contact_request_count_matches_consent',len(cases)==(1 if expected else 0)),
        check('chat_remains_available',not conversation.is_paused and not lead.is_opt_out),
        check('no_callback_or_transfer_promise',not re.search(r'will (?:call|contact)|within \d|have (?:transferred|connected) you',row['reply'],re.I))]
    if expected:
        checks.append(check('request_visible_to_staff',any(c['id']==cases[0].id for c in review_snapshot(db,conversation)['intervention_cases'])))
        checks.append(check('request_status',cases[0].status==('cancelled' if scenario=='human_withdrawal' and index>=2 else 'open')))
        pending=db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').all()
        checks.append(check('no_marketing_or_inactivity_after_insistence',not any(j.kind=='inactivity' or j.reason.endswith('_cadence') for j in pending)))
    if row['lead_message']==FAREWELL:checks.append(check('farewell_does_not_ask_another_question','?' not in row['reply']))
    if row['lead_message']=='What financing options do you offer?':checks.append(check('actual_question_answered','Bank financing' in row['reply']))
    if scenario=='mixed_human_price' and index==0:checks.append(check('mixed_price_answered','780,000.00 USD' in row['reply']))
    if scenario=='decline_visit_questions' and index==0:checks.append(check('decline_does_not_reinvite_visit','Would you like to review visit options' not in row['reply']))
    if scenario=='unavailable_then_close' and index==1:checks.append(check('unavailability_closure_invites_other_question','another property question' in row['reply']))
    return checks


async def evaluate_case(db,manifest,scenario,budget,max_turns):
    return await evaluate_commercial(db,manifest,scenario,budget,max_turns,scenarios=SCENARIOS,extra_checks=extra_checks)
