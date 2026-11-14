"""Scripted needs-first conversations, with explicit semantic assertions.

Run through the current core; no buyer/judge model, transport or real contacts.
The provider is real in the server CLI and simulated only in offline tests.
"""
from datetime import datetime, timedelta
from app.modules.sales_agent.needs_search import criterion

VERSION='sales-needs-discovery/1.0'
SPECS={
 'exact_two':(1,['I am looking for a 2 bedroom'],None),
 'house_two':(1,['Im looking for a 2 bedroom house'],None),
 'word_two':(1,["I'm looking for a two-bedroom home."],None),
 'show_two':(1,['Please show me 2 bedroom homes.'],None),
 'need_three':(2,['I need a 3 bedroom home.'],None),
 'multiple_two':(1,['Do you have any 2 bedroom homes?'],'multiple'),
 'no_two':(0,['I am looking for a 2 bedroom home.'],None),
 'unknown_bedrooms':(0,['I am looking for a 2 bedroom home.'],'unknown'),
 'sold_out_four':(2,['I am looking for a 4 bedroom home.'],None),
 'unconfirmed_inventory':(2,['I am looking for a 2 bedroom home.'],None),
 'change_need':(1,['I am looking for a 2 bedroom home.','Actually, I need a 1 bedroom home.'],None),
 'no_premature_selection':(1,['I am looking for a 2 bedroom home.','I am looking for a 1 bedroom home.'],None),
}
CASES=tuple(SPECS)


def prepare_case(db, manifest, scenario):
    from app.modules.projects.models import Project,ProjectPropertyType
    from app.modules.onboarding_versions import publish
    pi,script,variant=SPECS[scenario];project=db.get(Project,manifest['projects'][pi]['id'])
    if db.get_bind().dialect.name!='sqlite' or not project.is_demo:raise PermissionError('Needs experiments require disposable synthetic SQLite data.')
    from .synthetic_fixtures import identifier
    extra=db.get(ProjectPropertyType,identifier('needs-garden-home'))
    if extra:db.delete(extra);db.flush()
    # Fixtures remain synthetic and each scenario restores its own approved base.
    originals={p['id']:p for p in manifest['projects'][pi]['properties']}
    for row in db.query(ProjectPropertyType).filter_by(project_id=project.id):
        row.bedrooms=originals[row.id]['bedrooms']
    if variant=='multiple':
        db.add(ProjectPropertyType(id=identifier('needs-garden-home'),project_id=project.id,name='Cedar Garden Home',bedrooms=2,bathrooms=2,area_min=90,area_max=90,area_unit='m²',starting_price=285000,currency='USD',available_units=2,inventory_updated_at=datetime.utcnow(),review_status='confirmed',sort_order=2,description='Two-bedroom garden home for isolated discovery tests.',features=['Private patio'],images_status='not_available'))
    if variant=='unknown':
        db.get(ProjectPropertyType,manifest['projects'][pi]['properties'][0]['id']).bedrooms=None
    db.flush();publish(db,project.profile);db.commit()
    return project,script


def assertions(text,reply,metadata,context,selected):
    from .evaluation_checks import check,internal_process_narration
    need=criterion(text)
    expected=[p for p in context['property_types'] if p.get('bedrooms')==need['bedrooms'] and p.get('available_units')!=0]
    actual=metadata.get('needs_search') or {}
    names=[p['property_type'] for p in expected]
    wrong=[p['property_type'] for p in context['property_types'] if p['property_type'] not in names]
    return [check('needs_filter_executed',actual.get('bedrooms')==need['bedrooms']),
        check('exact_matching_ids',set(actual.get('matching_property_ids',[]))=={p['id'] for p in expected}),
        check('matches_explained',all(n in reply for n in names)),
        check('unmatched_names_not_presented',all(n not in reply for n in wrong)),
        check('bedroom_need_acknowledged',f"{need['bedrooms']}-bedroom" in reply or f"{need['bedrooms']} bedrooms" in reply),
        check('no_generic_model_clarification','which property option do you mean' not in reply.lower()),
        check('no_internal_provenance_or_processing',not internal_process_narration(reply) and not any(s in reply.lower() for s in ['approved project information highlights','property_details:','in this query'])),
        check('no_automatic_property_selection',selected is None),
        check('uncertain_inventory_not_claimed_available',all('availability' in reply.lower() and 'confirmation' in reply.lower() for p in expected if p.get('available_units') is None or not p.get('inventory_updated_at'))),
        check('incomplete_catalog_not_exhaustive',not (any(p.get('bedrooms') is None for p in context['property_types']) or not context['catalog_coverage'].get('exhaustive')) or ('incomplete' in reply.lower() or 'missing' in reply.lower()))]


async def evaluate_case(db,manifest,scenario,budget,max_turns):
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesConversation,SalesMessage,AgentRun,OutboundMessage
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.commercial_context import build_commercial_context
    from app.modules.sales_agent.dialogue_store import Scope,load
    from .evaluation_checks import check
    project,script=prepare_case(db,manifest,scenario)
    lead=Lead(company_id=project.company_id,project_id=project.id,full_name='Synthetic needs '+scenario,phone='+1555040'+str(1000+CASES.index(scenario)),platform='evaluation',is_demo=True,is_test=True,consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=project.company_id,project_id=project.id,lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False)
    db.add(conversation);db.commit();rows=[]
    for i,text in enumerate(script[:max_turns]):
        event=f'needs:{scenario}:{i}'
        before={m.id for m in db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound')}
        await turn(db,company_id=project.company_id,lead_id=lead.id,inbound_text=text,event_id=event,virtual_now=datetime.utcnow()+timedelta(seconds=i*10))
        run=db.query(AgentRun).filter_by(event_id=event).one()
        reply='\n\n'.join(m.content for m in db.query(SalesMessage).filter(SalesMessage.conversation_id==conversation.id,SalesMessage.direction=='outbound',~SalesMessage.id.in_(before)).order_by(SalesMessage.created_at,SalesMessage.id))
        context=build_commercial_context(db,project=project,company_id=project.company_id,lead_id=lead.id,channel='simulation')
        _,state=load(db,Scope(company_id=project.company_id,project_id=project.id,conversation_id=conversation.id,lead_id=lead.id))
        meta=(run.output_snapshot or {}).get('metadata') or {}
        checks=assertions(text,reply,meta,context,state.selected_property_type_id)
        checks += [check('turn_completed',not run.error_code),check('composition_accepted',(meta.get('composition') or {}).get('status')=='accepted')]
        from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
        event_row=db.query(SalesDialogueEvent).filter_by(conversation_id=conversation.id,kind='understanding_preview').order_by(SalesDialogueEvent.revision.desc()).first()
        attempts=(event_row.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) if event_row else []
        audit=[{k:a[k] for k in ('attempt','outcome','error_code','validation_issues','normalizations','raw_response_sha256') if k in a} for a in attempts]
        rows.append({'turn':i+1,'lead_message':text,'reply':reply,'understanding':(run.input_snapshot or {}).get('understanding'),'needs_search':meta.get('needs_search'),'read_authorization':(run.input_snapshot or {}).get('needs_read_authorization'),'interpretation_attempts':audit,'catalog_used':{'property_types':context['property_types'],'coverage':context['catalog_coverage'],'approved_revision':context.get('approved_revision')},'checks':checks})
    checks=[check('all_script_turns_completed',len(rows)==len(script)),check('no_booking',db.query(Meeting).filter_by(lead_id=lead.id).count()==0),check('no_provider_outbox',db.query(OutboundMessage).filter_by(conversation_id=conversation.id).count()==0)]
    passed=all(c['status']=='PASS' for r in rows for c in r['checks']) and all(c['status']=='PASS' for c in checks)
    return {'case':scenario,'project_id':project.id,'lead_id':lead.id,'conversation_id':conversation.id,'turns':rows,'checks':checks,'technical_execution':'PASS' if all(c['status']=='PASS' for r in rows for c in r['checks'] if c['check']=='turn_completed') else 'FAIL','needs_dialogue_checks':'PASS' if passed else 'FAIL','overall_dialogue_quality':'NOT_EVALUATED','meetings':[]}
