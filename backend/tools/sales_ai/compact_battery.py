"""Sixteen bounded, independent scripted buyers through the current Sales core.

Expected outcomes never enter the model context or the public-option driver.
No buyer model, judge, production writes, transport or external calendar.
"""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import re

VERSION='sales-compact-battery/1.0'
GOODBYE='No other questions, thank you. Goodbye.'
PERSONAS=(
 {'key':'first_time','name':'Emma Torres','segment':'first_time_buyer','motive':'I am buying my first home.','budget':300000},
 {'key':'move_up','name':'Daniel Brooks','segment':'move_up_buyer','motive':'I want to move from my current small home to a larger home.','budget':900000},
 {'key':'relocation','name':'Sofia Reed','segment':'relocation','motive':'I am relocating to this area for work and need a home here.','budget':900000},
 {'key':'downsizing','name':'Martin Vega','segment':'downsizing','motive':'I want to downsize from my large home to a smaller home.','budget':300000},
 {'key':'rental','name':'Lucas Chen','segment':'rental_yield_investor','motive':'I am buying an investment property to earn rental income.','budget':500000},
 {'key':'resale','name':'Valeria Cruz','segment':'appreciation_resale_investor','motive':'I am investing in a property for long-term appreciation and later resale.','budget':900000},
 {'key':'portfolio','name':'Adrian Park','segment':'portfolio_diversification','motive':'I want to diversify my investment portfolio by adding real estate.','budget':400000},
 {'key':'unknown','name':'Alex Rivera','segment':None,'motive':'','budget':500000},
)


def visit(name):
    return f'I would like to arrange an in-person visit to {name}. Any available time in the next seven days works for me. Please use the project timezone.'


def definitions():
    # Project/type indexes select only synthetic fixtures. The buyer knows the
    # property names it asks about, but never the private slot IDs or seller list.
    positives=[(1,1,'single','pdf'),(0,0,'all','gallery'),(0,0,'multi',None),
        (1,1,'single','pdf'),(2,0,'all',None),(0,0,'multi',None),
        (1,0,'single','gallery'),(2,0,'all',None)]
    names={(0,0):'Bay Residence',(1,0):'Cedar Loft',(1,1):'Cedar Studio',(2,0):'Ridge Townhome'}
    specs={}
    for persona,(pi,ti,access,material) in zip(PERSONAS,positives):
        name=names[pi,ti];budget=persona['budget']
        question=f'What can you tell me about {name}?'
        if persona['key']=='relocation':question=f'Where is {name} located and when is delivery planned?'
        if persona['key']=='portfolio':question='Please compare Cedar Loft and Cedar Studio.'
        first=' '.join(v for v in [persona['motive'],f'My budget is {budget:,} USD, paying cash.',question] if v)
        phases=[('information',first)]
        if material:phases.append(('material',f'Please send the {"photos" if material=="gallery" else "brochure PDF"} for {name}.'))
        phases.append(('request_visit',visit(name)))
        specs[persona['key']+'_A']={'persona':persona,'project':pi,'type':ti,'goal':'booked','access':access,
            'phases':phases,'budget':budget,'cash':True,'material':material,'choose':2 if persona['key']=='portfolio' else 1}
    def b(key,pi,ti,phases,**kwargs):
        persona=next(p for p in PERSONAS if p['key']==key)
        phases=[(a,(persona['motive']+' '+t).strip() if i==0 else t) for i,(a,t) in enumerate(phases)]
        specs[key+'_B']={'persona':persona,'project':pi,'type':ti,'goal':'closed','access':'all','phases':phases,
            'budget':kwargs.pop('budget',persona['budget']),'cash':kwargs.pop('cash',True),**kwargs}
    b('first_time',1,1,[('initial','I have 50,000 USD for a down payment. What financing options do you offer?'),
        ('material','My total purchase budget is 250,000 USD. Please send the brochure PDF for Cedar Studio.'),
        ('decline','I do not want a visit yet.'),('farewell',GOODBYE)],budget=250000,cash=False,material='pdf',initial_only=True)
    b('move_up',1,0,[('information','My budget is 400,000 USD, paying cash. Please show me Cedar Studio.'),
        ('switch','Actually I prefer Cedar Loft instead. Please send its photos.'),
        ('decline','I do not want a visit yet.'),('farewell',GOODBYE)],budget=400000,material='gallery',switch=True)
    b('relocation',0,0,[('information','My budget is 900,000 USD, paying cash. Where is Bay Residence located?'),
        ('request_visit',visit('Bay Residence'))],goal_override='unavailable',access_override='unassigned')
    b('downsizing',2,0,[('information','My budget is 500,000 USD, paying cash. Show me Ridge Townhome.'),
        ('missing_material','Please send the photos for Ridge Townhome.'),('sold_out','Is Summit Villa available?'),('decline','I do not want a visit yet.'),('farewell',GOODBYE)],budget=500000,missing_material=True)
    b('rental',2,0,[('information','My budget is 500,000 USD, paying cash. Show me Ridge Townhome.'),
        ('unknown_returns','What annual rental yield or occupancy can you guarantee?'),('unknown_inventory','What price and availability can you confirm for Valley Apartment?'),('decline','I do not want a visit yet.'),('farewell',GOODBYE)],budget=500000,unknown_returns=True)
    b('resale',0,0,[('information','My budget is 500,000 USD and I need financing. What options can you offer?'),
        ('reservation','Can I reserve Bay Residence and pay the deposit here?'),('decline','I do not want a visit yet.'),('farewell',GOODBYE)],budget=500000,cash=False,financing=True)
    b('portfolio',1,0,[('information','My budget is 400,000 USD, paying cash. Please compare Cedar Loft and Cedar Studio.'),
        ('request_visit',visit('Cedar Loft'))],goal_override='unavailable',access_override='no_slots')
    b('unknown',0,0,[('human','I want to speak to a human'),('human_insist','I still want to speak to a human'),('farewell',GOODBYE)],budget=None,cash=False,human=True)
    for spec in specs.values():
        spec['goal']=spec.pop('goal_override',spec['goal']);spec['access']=spec.pop('access_override',spec['access'])
    return specs

SPECS=definitions()
CASES=tuple(f'{p["key"]}_{suffix}' for p in PERSONAS for suffix in ('A','B'))


def team(db,manifest,key,clock):
    from app.modules.users.models import User,UserRole
    from app.modules.users.project_access import sync_user_project_access
    from app.modules.project_team.models import ProjectUserAssignment,ProjectRoutingState
    from app.modules.sales_crm.models import SalesAvailabilityBlock,CalendarConnection
    from .synthetic_fixtures import identifier
    if db.bind.dialect.name!='sqlite':raise PermissionError('Compact battery requires a private SQLite database.')
    for cls in (CalendarConnection,SalesAvailabilityBlock,ProjectRoutingState,ProjectUserAssignment):db.query(cls).delete(synchronize_session=False)
    spec=SPECS[key];target=manifest['projects'][spec['project']]['id']
    other=manifest['projects'][(spec['project']+1)%3]['id'];roster=[]
    for role in ('candidate','other_project','none','inactive','no_appointments'):
        scope='selected';ids=[];active=role!='inactive';accepts=role!='no_appointments'
        if role=='candidate':
            if spec['access']=='all':scope='all'
            elif spec['access']=='multi':ids=[target,other]
            elif spec['access']!='unassigned':ids=[target]
        elif role=='other_project':ids=[other]
        elif role in {'inactive','no_appointments'}:ids=[target]
        user=User(id=identifier('compact-'+key+'-'+role),company_id=manifest['company_id'],
            first_name='Synthetic',last_name=role,email=key+'-'+role+'@compact.synthetic.invalid',
            hashed_password='DISABLED-NOT-A-LOGIN',role=UserRole.SALES,is_active=active,project_access_scope=scope)
        db.add(user);db.flush()
        sync_user_project_access(db,user=user,scope=scope,project_ids=ids,allow_empty_selected=True,
            sales_enabled=True,accepts_appointments=accepts,accepts_new_leads=True)
        has_slots=not (role=='candidate' and spec['access']=='no_slots')
        if has_slots:
            for day in (2,3,4):
                start=(clock+timedelta(days=day)).replace(hour=15,minute=0,second=0,microsecond=0)
                db.add(SalesAvailabilityBlock(user_id=user.id,starts_at=start,ends_at=start+timedelta(hours=3),timezone='UTC'))
        roster.append({'id':user.id,'company_id':user.company_id,'role':role,'active':active,'access_scope':scope,
            'project_ids':ids,'accepts_appointments':accepts,'has_slots':has_slots})
    db.commit();return roster


def public_next(reply,history,name,choose=1):
    """Only public wording and the buyer's own preference authorize a selection."""
    if re.search(r'please confirm your visit',reply,re.I):
        if not history or history[-1]['action']!='select':return None,'confirmation_without_selection'
        chosen=history[-1].get('lead_message','').split('appointment: ',1)
        if len(chosen)!=2 or chosen[1].rstrip('.') not in reply or name not in reply:
            return None,'confirmation_changed_public_selection'
        return 'Yes','confirm'
    options=re.findall(r'^\s*\d+\.\s*(\d{4}-\d{2}-\d{2} at [^\n]+)',reply,re.M)
    if options:
        if len(options)<choose:return None,'preferred_option_not_offered'
        ordinal=('first','second','third')[choose-1]
        return (('The first time does not work for me. ' if choose==2 else '')+f'I would like the {ordinal} appointment: '+options[choose-1]+'.'),'select'
    if re.search(r'which (?:property|unit)|which location',reply,re.I):return visit(name),'clarify_property'
    return visit(name),'clarify_visit'


def resources(db,manifest,lead,property_id,rows):
    import hashlib
    from app.modules.projects import asset_share_service
    from app.modules.projects.models import ProjectSalesAsset,SalesAssetShare
    from app.modules.projects.property_resource_service import read_resource
    from .evaluation_checks import check
    from app.core.config import settings
    prefix=f"{settings.PUBLIC_APP_URL.rstrip('/')}{settings.API_V1_STR}/projects/a/"
    urls=[];receipts=[];checks=[]
    public_urls=[u.rstrip('.,);') for row in rows for u in re.findall(r'https?://[^\s]+',row.get('reply',''))]
    checks.append(check('only_registered_material_urls',all(u.startswith(prefix) and re.fullmatch(r'[A-Za-z0-9_-]+',u[len(prefix):]) for u in public_urls)))
    for row in rows:
        for token in re.findall(r'https?://[^\s]+/projects/a/([A-Za-z0-9_.-]+)',row.get('reply','')):
            token=token.rstrip('.,);')
            if token not in urls:urls.append(token)
    for token in urls:
        try:
            source,share=asset_share_service.resolve(db,token)
            asset=db.get(ProjectSalesAsset,share.sales_asset_id)
            scoped=(share.company_id==lead.company_id and share.project_id==lead.project_id and share.lead_id==lead.id)
            checks.append(check('material_link_scope',scoped))
            checks.append(check('material_link_property',bool(asset and asset.property_type_id==property_id)))
            content,mime,_=read_resource(source)
            mime=mime.split(';',1)[0]
            receipts.append({'share_id':share.id,'asset_id':asset.id,'property_type_id':asset.property_type_id,
                'mime_type':mime,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content),'laboratory_only':True,'local_material_path':next((r['path'] for p in manifest['projects'] for t in p['properties'] for r in t.get('resources',[]) if r['asset_id']==asset.id),None)})
            checks.append(check('material_bytes_readable',bool(content) and mime in {'application/pdf','text/html'}))
        except Exception:
            checks.append(check('issued_material_link_resolves_in_private_database',False))
    shares=db.query(SalesAssetShare).filter_by(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id).all()
    checks.append(check('no_unregistered_material_link',len(urls)==len(receipts)))
    checks.append(check('all_shares_bound_to_current_property',all((db.get(ProjectSalesAsset,s.sales_asset_id) is not None and db.get(ProjectSalesAsset,s.sales_asset_id).property_type_id==property_id) for s in shares)))
    return receipts,checks


async def evaluate_case(db,manifest,key,budget,max_turns):
    from sqlalchemy.orm import Session
    from app.modules.sales_crm.models import Lead,Meeting
    from app.modules.sales_agent.models import SalesConversation,SalesMessage,AgentRun,OutboundMessage
    from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
    from app.modules.sales_agent.current_simulation import turn
    from app.modules.sales_agent.lead_profile import resolve
    from app.modules.sales_agent.profile_intelligence import segment_for,budget_cap
    from app.modules.project_team.service import eligible_appointment_assignments
    from app.modules.governance.models import HumanInterventionCase
    from .evaluation_checks import check,error_details,internal_process_narration
    from .commercial_pilot import quality_checks
    from .booking_pilot import explains_unavailability
    spec=SPECS[key];persona=spec['persona'];project=manifest['projects'][spec['project']];prop=project['properties'][spec['type']]
    clock=datetime.utcnow();roster=team(db,manifest,key,clock)
    eligible={a.user_id for a in eligible_appointment_assignments(db,project['id'])}
    expected_eligible={r['id'] for r in roster if r['role']=='candidate' and spec['access']!='unassigned'}
    lead=Lead(company_id=manifest['company_id'],project_id=project['id'],full_name=persona['name'],phone='+1555030'+str(CASES.index(key)+1000),
        platform='evaluation',is_demo=True,is_test=True,consent_status='granted_simulation',preferred_channel='simulation',agent_status='simulation',pipeline_stage='S01_RESEARCH')
    db.add(lead);db.flush()
    conversation=SalesConversation(company_id=manifest['company_id'],project_id=project['id'],lead_id=lead.id,channel='simulation',provider='simulation',is_paused=False)
    db.add(conversation);db.commit()
    checks=[check('segment_not_seeded',lead.assigned_segment is None),check('eligible_roster_matches_assignments',eligible==expected_eligible)]
    rows=[];phase=0;selected_start=None;selected_label=None;confirmed=False;visit_requested=False;acked=False;stop='turn_limit';last='';last_event=None
    for index in range(max_turns):
        if budget.calls>=budget.maximum:stop='call_budget';break
        if phase<len(spec['phases']):action,message=spec['phases'][phase];phase+=1
        elif spec['goal']=='booked':message,action=public_next(last,rows,prop['name'],spec.get('choose',1))
        elif spec['goal']=='unavailable':
            if acked:message,action=GOODBYE,'farewell'
            elif explains_unavailability(last):message,action='Understood, thank you. Please do not book anything or set up an alert now.','acknowledge_unavailable';acked=True
            else:message,action=visit(prop['name']),'clarify_visit'
        else:stop='script_completed';break
        if not message:stop=action;break
        if sum(r.get('lead_message')==message for r in rows)>=2:stop='repeated_message_without_progress';break
        visit_requested |= action in {'request_visit','clarify_visit','clarify_property'}
        if action=='select':
            selected_label=message
            match=re.search(r'(\d{4}-\d{2}-\d{2} at \d{2}:\d{2} [AP]M) \(([^,]+),',message)
            if match:selected_start=datetime.strptime(match[1],'%Y-%m-%d at %I:%M %p').replace(tzinfo=ZoneInfo(match[2])).astimezone(timezone.utc).replace(tzinfo=None)
        if action=='confirm':confirmed=True
        last_event='compact:'+key+':'+str(index)
        before={m.id for m in db.query(SalesMessage).filter_by(conversation_id=conversation.id,direction='outbound')}
        try:
            await turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=message,event_id=last_event,virtual_now=clock+timedelta(seconds=10*(index+1)))
            run=db.query(AgentRun).filter_by(event_id=last_event).one()
            outgoing=db.query(SalesMessage).filter(SalesMessage.conversation_id==conversation.id,SalesMessage.direction=='outbound',~SalesMessage.id.in_(before)).order_by(SalesMessage.created_at,SalesMessage.id).all()
            last='\n\n'.join(m.content for m in outgoing)
            events=db.query(SalesDialogueEvent).filter_by(conversation_id=conversation.id,kind='understanding_preview').order_by(SalesDialogueEvent.revision).all()
            attempts=next(((e.payload_json.get('metadata') or {}).get('interpretation_attempts',[]) for e in reversed(events) if (e.payload_json.get('metadata') or {}).get('inbound_message_id')==(run.input_snapshot or {}).get('message_id')),[])
            if not attempts:attempts=((run.input_snapshot or {}).get('interpretation_failure') or {}).get('interpretation_attempts',[])
            db.commit()
            with Session(bind=db.get_bind(),autoflush=False) as reader:
                fresh=reader.get(Lead,lead.id);profile=resolve(fresh);actual_segment=segment_for(fresh);assigned=fresh.assigned_segment;cap=budget_cap(profile)
            meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
            frame=(run.input_snapshot or {}).get('understanding') or {};meta=(run.output_snapshot or {}).get('metadata') or {}
            row_checks=[check('current_workflow',(run.output_snapshot or {}).get('workflow_version')=='sales-current/1.0'),
                check('turn_completed',not run.error_code),check('scripted_english_not_rejected',not meta.get('language_hold')),check('reply_present',bool(last.strip())),check('no_internal_narration',not internal_process_narration(last)),
                check('segment_matches_declared_motivation',actual_segment==persona['segment'] and assigned==persona['segment'],f"expected={persona['segment']}; actual={actual_segment}; assigned={assigned}"),
                check('no_booking_without_confirmation',not meetings or (confirmed and selected_start is not None and visit_requested)),
                check('at_most_one_booking',len(meetings)<=1),check('no_identical_consecutive_reply',not rows or last!=rows[-1]['reply'])]
            composition=meta.get('composition') or {}
            if composition:row_checks.append(check('composition_accepted',composition.get('status')=='accepted'))
            row_checks+=quality_checks(message,last,frame)
            if persona['segment']:
                classified=[r for f,r in profile['current'].items() if f in {'buyer_type','motivation'} and (r.get('normalized_segment') or r.get('value'))==persona['segment']]
                first_id=(rows[0]['input_trace'].get('message_id') if rows else (run.input_snapshot or {}).get('message_id'))
                row_checks.append(check('segment_evidence_from_own_initial_declaration',bool(classified) and all((r.get('source_ref') or {}).get('message_id')==first_id and r.get('evidence') in spec['phases'][0][1] for r in classified)))
            if spec.get('initial_only') and index==0:row_checks.append(check('down_payment_not_total_budget',cap is None))
            elif spec['budget'] is not None:
                row_checks.append(check('declared_budget_persists',cap is not None and cap[0]==spec['budget'] and cap[1]=='USD'))
                row_checks.append(check('known_budget_not_asked_again',not re.search(r'What budget range and currency',last,re.I)))
            if spec['cash']:
                funding=profile['current']['financing'];row_checks.append(check('cash_preference_persists',funding['status']=='declared' and bool(re.search(r'cash|outright',str(funding.get('value') or ''),re.I))))
            if action in {'material','switch'} and spec.get('material'):
                row_checks.append(check('material_request_delivered_this_turn',bool(meta.get('sales_asset_share_ids') or (run.output_snapshot or {}).get('sales_asset_share_ids'))))
            if action in {'material','request_visit','select'}:
                row_checks.append(check('no_comparison_invented_for_action',not frame.get('comparison')))
            if key=='move_up_B' and index==0:
                initial=manifest['projects'][1]['properties'][1]
                row_checks.append(check('initial_named_property_scope',named_property_answered(last,meta,initial,manifest['projects'][1]['properties'])))
                row_checks.append(check('information_does_not_request_visit',frame.get('visit') is None))
            if action=='select':row_checks.append(check('selection_advances_to_confirmation','Please confirm your visit' in last))
            if action=='decline' and not meetings:
                row_checks.append(check('decline_not_misread_as_existing_visit_change',not re.search(r'cancel the current visit|request a different visit|which .*visit.*cancel',last,re.I)))
            if action=='farewell':row_checks.append(check('no_question_after_goodbye','?' not in last))
            if spec.get('human') and action in {'human_insist','farewell'}:
                count=db.query(HumanInterventionCase).filter_by(company_id=lead.company_id,project_id=lead.project_id,lead_id=lead.id,conversation_id=conversation.id,reason='HUMAN_CONTACT_REQUEST',status='open').count()
                row_checks.append(check('human_request_saved_once',count==1))
            rows.append({'turn':index+1,'action':action,'lead_message':message,'reply':last,'profile':profile,'assigned_segment':assigned,
                'understanding':frame,'interpretation_attempts':attempts,'input_trace':run.input_snapshot,'output':run.output_snapshot,'error_code':run.error_code,'checks':row_checks})
            if meetings:stop='booked';break
            if action=='decline' and not meetings:
                row_checks.append(check('decline_not_misread_as_existing_visit_change',not re.search(r'cancel the current visit|request a different visit|which .*visit.*cancel',last,re.I)))
            if action=='farewell':stop='closed';break
        except Exception as exc:
            db.rollback();rows.append({'turn':index+1,'action':action,'lead_message':message,**error_details(exc),'checks':[check('engine_turn_completed',False)]});stop='engine_error';break
    meetings=db.query(Meeting).filter_by(lead_id=lead.id).all()
    checks.extend([check('expected_booking_outcome',len(meetings)==(1 if spec['goal']=='booked' else 0)),check('no_provider_outbox',db.query(OutboundMessage).count()==0),
        check('dialogue_reached_terminal_outcome',stop=='booked' if spec['goal']=='booked' else stop=='closed')])
    if meetings:
        meeting=meetings[0]
        checks.extend([check('eligible_sales_user',meeting.assigned_sales_user_id in expected_eligible),check('correct_lead_and_project',meeting.lead_id==lead.id and meeting.project_id==project['id']),
            check('time_matches_public_choice',meeting.meeting_time==selected_start),check('project_timezone_offered',project['timezone'] in (selected_label or '')),
            check('location_recorded',f"{spec['project']+1} Synthetic Avenue" in (meeting.visit_address or '')),check('booked_property_matches_choice',meeting.visit_property_type_id==prop['id']),check('confirmation_stored',meeting.confirmation_status=='confirmed'),check('public_confirmation_matches_booking','Your visit is confirmed' in last)])
    material_receipts,material_checks=resources(db,manifest,lead,prop['id'],rows);checks+=material_checks
    if spec.get('material'):
        mime='text/html' if spec['material']=='gallery' else 'application/pdf'
        checks.append(check('requested_material_delivered',any(r['mime_type']==mime for r in material_receipts)))
    if spec.get('missing_material'):
        checks.extend([check('missing_material_not_invented',not material_receipts),check('missing_material_explained',any(re.search(r"(?:no|not|don.t|cannot|unavailable|unconfirmed|couldn.t).*(?:photo|image|gallery)|(?:photo|image|gallery).*(?:no|not|unavailable|unconfirmed)",r.get('reply',''),re.I) for r in rows))])
    if spec.get('unknown_returns'):
        reply=' '.join(r.get('reply','') for r in rows if r.get('action')=='unknown_returns')
        checks.extend([check('no_invented_yield_percentage',not re.search(r'\d+(?:\.\d+)?\s*%',reply)),
            check('unpublished_return_gap_explained',returns_gap_answered(reply))])
    if key=='downsizing_B':
        reply=' '.join(r.get('reply','') for r in rows if r.get('action')=='sold_out')
        checks.append(check('sold_out_status_answered',bool(re.search(r'last confirmed quantity:\s*0|(?:no|zero) .*(?:available|remaining)|sold out|not available',reply,re.I))))
    if key=='rental_B':
        reply=' '.join(r.get('reply','') for r in rows if r.get('action')=='unknown_inventory')
        checks.append(check('unknown_price_and_inventory_explicit',unknown_inventory_answered(reply)))
    if spec.get('financing'):checks.append(check('published_financing_answered',any('Bank financing' in r.get('reply','') for r in rows)))
    if spec['goal']=='unavailable':checks.extend([check('unavailability_explained',any(explains_unavailability(r.get('reply','')) for r in rows)),check('buyer_acknowledged_public_unavailability',acked)])
    if spec.get('switch'):checks.append(check('property_switch_reflected',any((r.get('output',{}).get('metadata',{}).get('selected_property_type_id')==prop['id']) for r in rows if r.get('action')=='switch')))
    if last_event and rows and stop in {'booked','closed'}:
        from app.modules.projects.models import SalesAssetShare
        before=(db.query(Meeting).filter_by(lead_id=lead.id).count(),db.query(SalesAssetShare).filter_by(lead_id=lead.id).count(),db.query(SalesMessage).filter_by(conversation_id=conversation.id).count(),budget.calls)
        await turn(db,company_id=lead.company_id,lead_id=lead.id,inbound_text=rows[-1]['lead_message'],event_id=last_event)
        after=(db.query(Meeting).filter_by(lead_id=lead.id).count(),db.query(SalesAssetShare).filter_by(lead_id=lead.id).count(),db.query(SalesMessage).filter_by(conversation_id=conversation.id).count(),budget.calls)
        checks.append(check('last_event_replay_is_idempotent',before==after))
    return {'case':key,'persona':persona,'lead_id':lead.id,'conversation_id':conversation.id,'project_id':project['id'],'property_type_id':prop['id'],'expected_outcome':spec['goal'],
        'team':roster,'eligible_sales_ids':sorted(eligible),'session_autoflush':db.autoflush,'profile_read_mode':'new_session_after_commit','stop_reason':stop,
        'turns':rows,'checks':checks,'materials':material_receipts,'meetings':[{'id':m.id,'lead_id':m.lead_id,'project_id':m.project_id,'sales_user_id':m.assigned_sales_user_id,
            'starts_at_utc':m.meeting_time.isoformat(),'duration_minutes':m.duration_minutes,'address':m.visit_address,'property_type_id':m.visit_property_type_id,'calendar_sync_status':m.calendar_sync_status} for m in meetings]}



def summarize(cases):
    """Compact factual outcomes, never a weighted or LLM-overridden score."""
    results=[]
    for case in cases:
        failures=[{'turn':None,'check':c['check'],'detail':c.get('detail','')} for c in case.get('checks',[]) if c['status']=='FAIL']
        failures += [{'turn':row['turn'],'check':c['check'],'detail':c.get('detail','')} for row in case.get('turns',[]) for c in row.get('checks',[]) if c['status']=='FAIL']
        results.append({'case':case['case'],'expected_outcome':case.get('expected_outcome'),
            'turns':len(case.get('turns',[])),'bookings':len(case.get('meetings',[])),
            'stop_reason':case.get('stop_reason'),'status':'FAIL' if failures else 'PASS','failures':failures})
    return results



def unknown_inventory_answered(reply):
    """Both missing fields must be explicit; a known buyer budget is not a price."""
    missing=r'(?:unconfirmed|not (?:yet )?(?:confirmed|published)|unknown|unavailable)'
    def field(label):
        return bool(re.search(label+r'[^.!?\n]{0,100}'+missing,reply,re.I) or
            re.search(r'(?:cannot|can.t|unable to) confirm[^.!?\n]{0,80}'+label,reply,re.I))
    return field(r'\b(?:price|pricing)\b') and field(r'\b(?:availability|inventory|quantity)\b') and not re.search(r'last confirmed quantity:\s*0',reply,re.I)


def returns_gap_answered(reply):
    for sentence in re.split(r'[.!?\n]',reply):
        if re.search(r'\b(?:yield|occupancy|returns?)\b',sentence,re.I) and re.search(r"\b(?:not|no|cannot|unavailable|unconfirmed)\b|can.t|don.t",sentence,re.I):return True
    return False


def named_property_answered(reply,metadata,expected,properties):
    """Catalog offers and resolved details are both valid evidence of scope."""
    offer=metadata.get('property_catalog_offer')
    if offer is not None:
        bound=offer.get('property_type_ids')==[expected['id']]
    else:
        refs=(metadata.get('planning') or {}).get('references',{}).values()
        bound=metadata.get('selected_property_type_id')==expected['id'] and any(
            r.get('status')=='resolved' and (r.get('value') or {}).get('property_id')==expected['id'] for r in refs)
    contains=lambda name:bool(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',reply,re.I))
    return bound and contains(expected['name']) and not any(contains(p['name']) for p in properties if p['id']!=expected['id'])
