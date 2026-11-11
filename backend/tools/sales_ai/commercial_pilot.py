"""Short scripted commercial dialogues through the deployed Sales coordinator."""
from datetime import datetime,timedelta

FAREWELL='No other questions, thank you. Goodbye.'
SCENARIOS={
    'cash_available':(0,['My budget is 900,000 USD. I have cash available and do not need financing. What can you tell me about Bay Residence?',FAREWELL],'none'),
    'outright_purchase':(0,['My budget is 900,000 USD and I will pay cash. Show me Bay Residence.',FAREWELL],'none'),
    'affordable_alternative':(1,['My budget is 250,000 USD. What property options fit my budget?',FAREWELL],'within_budget_alternative'),
    'lower_budget_financing':(0,['My budget is 500,000 USD and I need financing. What options can you offer?',FAREWELL],'discuss_published_financing'),
    'no_budget_match':(2,['My budget is 100,000 USD and I will pay cash. What property options fit my budget?',FAREWELL],'no_budget_match'),
    'down_payment_only':(1,['I have 50,000 USD for a down payment. What financing options do you offer?','My total purchase budget is 250,000 USD.',FAREWELL],'clarify_total_budget'),
    'different_currency':(0,['My budget is 500,000 EUR. What property options fit my budget?',FAREWELL],'currency_mismatch'),
    'property_reservation':(0,['Can I reserve Bay Residence and pay the deposit here?',FAREWELL],'in_person_commercial_transaction'),
}
CASES=tuple(SCENARIOS)


def prepare(db,manifest):
    """Change only the private synthetic approval, never a production project."""
    from app.modules.projects.models import Project
    from app.modules.onboarding_versions import publish
    assert db.bind.dialect.name=='sqlite'
    project=db.get(Project,manifest['projects'][2]['id'])
    assert project.is_demo
    project.profile.profile_data={**project.profile.profile_data,'payment_methods':['Cash only']}
    db.flush();publish(db,project.profile);db.commit()
    for entry in manifest['projects']:
        entry['published_payment_methods']=db.get(Project,entry['id']).profile.published_snapshot['data']['payment_methods']


async def evaluate_case(db,manifest,scenario,budget,max_turns):
    import re
    from sqlalchemy.orm import Session
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesMessage,AgentRun,OutboundMessage
    from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.lead_profile import resolve
    from app.modules.sales_agent.profile_intelligence import budget_cap
    from .evaluation_checks import check,internal_process_narration
    project_index,script,expected=SCENARIOS[scenario]
    project=manifest['projects'][project_index]
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name='Scripted '+scenario,
        phone='+1555020'+str(CASES.index(scenario)+1000),platform='evaluation',is_demo=True,is_test=True,
        consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.commit();rows=[];clock=datetime.utcnow()
    for index,message in enumerate(script[:max_turns]):
        if budget.calls>=budget.maximum:break
        event_id='commercial-pilot:'+scenario+':'+str(index)
        await turn(db,company_id=manifest['company_id'],lead_id=lead.id,inbound_text=message,event_id=event_id,
            virtual_now=clock+timedelta(seconds=10*(index+1)))
        run=db.query(AgentRun).filter_by(event_id=event_id).one()
        reply=(run.output_snapshot or {}).get('reply') or ''
        metadata=(run.output_snapshot or {}).get('metadata') or {}
        db.commit()
        with Session(bind=db.get_bind(),autoflush=False) as reader:profile=resolve(reader.get(Lead,lead.id))
        events=db.query(SalesDialogueEvent).filter_by(conversation_id=run.conversation_id,kind='understanding_preview').all()
        attempts=next(((e.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) for e in reversed(events)
            if (e.payload_json.get('metadata') or {}).get('inbound_message_id')==(run.input_snapshot or {}).get('message_id')),[])
        checks=[check('interpretation_accepted',not run.error_code),check('reply_present',bool(reply.strip())),
            check('no_internal_narration',not internal_process_narration(reply)),
            check('no_unrequested_meeting',db.query(Meeting).filter_by(lead_id=lead.id).count()==0),
            check('no_payment_or_property_reservation_receipt',not bool(re.search(r'your (?:property|unit) (?:is|has been) (?:reserved|held)|payment (?:received|accepted)',reply,re.I))),
            check('no_provider_outbox',db.query(OutboundMessage).count()==0)]
        if index==0:
            decision=(metadata.get('commercial_policy') or {}).get('decision')
            if expected!='none':checks.append(check('expected_commercial_outcome',decision==expected))
            if scenario=='down_payment_only':checks.append(check('initial_is_not_total_budget',budget_cap(profile) is None))
            elif scenario!='property_reservation':checks.append(check('explicit_total_budget_persisted',budget_cap(profile) is not None))
            if scenario=='affordable_alternative':checks.append(check('only_affordable_option_suggested',(metadata.get('commercial_policy') or {}).get('alternative_ids')==[project['properties'][1]['id']] and '210,000.00 USD' in reply))
            if scenario in {'cash_available','outright_purchase'}:checks.append(check('cash_is_without_financing',bool(re.search(r'outright purchase, without financing',reply,re.I))))
            if scenario=='lower_budget_financing':checks.append(check('published_financing_not_approval','Bank financing' in reply and 'does not guarantee approval' in reply))
            if scenario=='no_budget_match':checks.append(check('kind_close_without_financing_promise','good day' in reply and 'may be an option' not in reply))
            if scenario=='property_reservation':checks.append(check('property_hold_not_visit',not metadata.get('appointment_offer') and 'cannot take a payment or hold a property' in reply))
        rows.append({'turn':index+1,'lead_message':message,'reply':reply,'profile':profile,
            'error_code':run.error_code,'understanding':(run.input_snapshot or {}).get('understanding'),
            'input_trace':run.input_snapshot,'output':run.output_snapshot,'interpretation_attempts':attempts,'checks':checks})
    return {'case':scenario,'project_id':project['id'],'session_autoflush':db.autoflush,
        'profile_read_mode':'new_session_after_commit','turns':rows,
        'checks':[check('script_completed',len(rows)==len(script))],'stop_reason':'script_completed' if len(rows)==len(script) else 'call_or_turn_limit'}
