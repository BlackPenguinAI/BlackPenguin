"""Versioned rescheduling: preserve the original until an exact atomic replacement."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import re
from fastapi import HTTPException
from app.modules.projects.models import Project,ProjectPropertyType,ProjectUnit
from app.modules.projects.locations import resolve_visit_location,locations_for_project
from app.modules.sales_crm.models import Lead,Meeting,MeetingStatus,CalendarConnection
from app.modules.users.models import User
from app.modules.project_team.service import eligible_appointment_assignments
from app.modules.onboarding_versions import active_approved,require_capability
from .dialogue_store import Scope,check_scope
from .understanding_contract import Understanding,RescheduleDirective,VisitDirective,Task
from .reference_resolution import normalized
from .turn_configuration import digest
from .turn_memory import booking_digest
from .appointment_context import utc,bind_visit
from .first_booking import accepted_outbound,normalize_timing,search_slots,label,confirmation,stop_cadence
from .booking_models import SalesBookingOperation
from .reschedule_models import SalesRescheduleOperation

VERSION='sales-reschedule/1.0'


def reservation_version(row):
    return digest({'booking':booking_digest(row),'visit_context':row.visit_context,
        'confirmation_status':row.confirmation_status,'modality':row.modality})


def authorize_target(db,scope,project_id):
    from .active_service import selected_policy
    from .next_flow import selected
    from .sales_policy import policy_context,compliance_action_holds
    from .commercial_context import confirmed_profile_facts
    check_scope(db,scope)
    project=db.query(Project).filter_by(id=project_id,company_id=scope.company_id).populate_existing().one_or_none()
    if not project:raise PermissionError('That Project is not available for this change.')
    target_scope=replace(scope,project_id=project_id)
    if not selected(target_scope) or not selected_policy(db,target_scope):raise PermissionError('That Project is not enabled for this visit change.')
    if project.profile:db.refresh(project.profile);require_capability(project.profile,'appointments')
    if project_id!=scope.project_id and not active_approved(project.profile):raise PermissionError('The target Project needs explicit approval.')
    holds=compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile),target_project_id=project_id))
    if 'appointment' in holds:raise PermissionError('The Sales team needs to review that visit change under approved guidance.')
    return project,target_scope


def meeting_snapshot(db,row):
    project=db.get(Project,row.project_id);user=db.query(User).filter_by(id=row.assigned_sales_user_id,company_id=project.company_id).first() if row.assigned_sales_user_id else None
    stored=row.visit_context or {}
    return {'id':row.id,'project_id':row.project_id,'project_name':stored.get('project_name') or project.name,
        'property_type_id':row.visit_property_type_id,'unit_id':row.visit_unit_id,
        'property_type_name':stored.get('property_type_name'),'unit_code':stored.get('unit_code'),
        'starts_at':utc(row.meeting_time).isoformat(),'duration_minutes':row.duration_minutes,
        'sales_user_id':row.assigned_sales_user_id,'specialist_name':' '.join(v for v in [user.first_name,user.last_name] if v) if user else None,
        'timezone':stored.get('timezone') or project.timezone or 'UTC',
        'location':{'label':row.visit_location_label or 'Visit location','address':row.visit_address or 'Address not recorded'},
        'status':row.status.value,'booking_sha256':reservation_version(row)}


def current_description(snapshot):
    property_name=snapshot['project_name']+(' / '+snapshot['property_type_name'] if snapshot.get('property_type_name') else '')
    if snapshot.get('unit_code'):property_name+=' / unit '+snapshot['unit_code']
    option={'starts_at':snapshot['starts_at'],'specialist_name':snapshot.get('specialist_name') or 'Specialist not recorded'}
    try:when=label(option,{'timezone':snapshot['timezone']})
    except Exception:when=snapshot['starts_at']+' (UTC); '+option['specialist_name']
    return f"{property_name}; {when}; {snapshot['duration_minutes']} minutes; {snapshot['location']['address']}"


def comparison(proposal,*,confirmed=False):
    old=current_description(proposal['original'])
    target=confirmation(proposal['target_context'],proposal['option'],proposal['preferences']).removeprefix('Please confirm your visit: ').removesuffix(' Shall I book this exact visit?')
    if proposal['target_context'].get('property_type_name'):target=proposal['target_context']['project_name']+' / '+target
    if confirmed:return 'Your visit has been rescheduled. Previous visit: '+old+'. Replacement visit: '+target+' Your earlier reservation has been replaced. What else would you like to know?'
    return 'Current visit: '+old+'.\n\nProposed replacement: '+target+'\n\nYour current reservation stays in place until this change is confirmed. Shall I replace it with this exact visit?'


def originals(db,scope):
    return db.query(Meeting).join(Project,Project.id==Meeting.project_id).filter(
        Project.company_id==scope.company_id,Meeting.lead_id==scope.lead_id,
        Meeting.status.in_([MeetingStatus.SCHEDULED,MeetingStatus.CONFIRMED]),Meeting.meeting_time>datetime.utcnow()).order_by(Meeting.meeting_time,Meeting.id).all()


def resolve_original(db,scope,conversation,directive,state,*,offer_key='reschedule_meeting_offer'):
    rows=originals(db,scope);reference=directive.meeting_reference if directive else None
    if reference:
        from .turn_context import choice_index
        cleaned=re.sub(r'\b(?:appointment|visit|booking)\b','',normalized(reference)).strip()
        index=choice_index(cleaned)
        offered=accepted_outbound(db,conversation,offer_key)
        ids=(offered.metadata_json or {})[offer_key]['meeting_ids'] if offered else []
        if index is not None:
            if not 0<=index<len(ids):return None,rows
            return next((r for r in rows if r.id==ids[index]),None),rows
        value=normalized(reference)
        matches=[]
        for row in rows:
            data=meeting_snapshot(db,row)
            if value in {normalized(str(v)) for v in [data['project_name'],data.get('property_type_name'),data.get('unit_code'),row.meeting_time.date().isoformat()] if v}:
                matches.append(row)
        return (matches[0] if len(matches)==1 else None),rows
    stored=state.reschedule_search.get('original_meeting_id')
    if stored:return next((r for r in rows if r.id==stored),None),rows
    return (rows[0] if len(rows)==1 else None),rows


def directive_for(u):
    if u.reschedule:return u.reschedule
    if u.visit and u.visit.action=='reschedule':return RescheduleDirective(action='request',evidence=u.visit.evidence,timing=u.visit.timing)
    return None


def should_handle(u,state,previous_meta,outcome=None):
    if u.reschedule or u.visit and u.visit.action=='reschedule':return True
    if not u.permits('appointment') or u.appointment_query:return False
    if any(previous_meta.get(k) for k in ['reschedule_offer','reschedule_confirmation','reschedule_meeting_offer','reschedule_context_question']):return True
    refs=(getattr(outcome,'plan',None) or {}).get('references',{})
    return bool(state.reschedule_search and any(r.get('value',{}).get('kind')=='appointment' for r in refs.values()))


def enrich(u,previous_meta,text):
    from .service import _affirmative_slot_reply
    normalized_reply=' '.join(re.sub(r'[^a-z ]',' ',text.casefold()).split())
    decline=normalized_reply in {'no','no thanks','no thank you','not now'}
    key=next((k for k in ['reschedule_confirmation','reschedule_offer','reschedule_meeting_offer','reschedule_context_question'] if previous_meta.get(k)),None)
    if key=='reschedule_meeting_offer' and not decline:
        from .turn_context import choice_index
        if choice_index(text) is not None:
            payload=u.model_dump(mode='json')
            payload.update(requests=[{'id':'choose_current_visit','topic':'appointment','subject':None,'polarity':'request','evidence':text}],
                all_of=['choose_current_visit'],alternatives=[],references=[],selected_reference_id=None,
                requires_clarification=False,clarification_question=None,appointment_query=None,visit=None,
                reschedule={'action':'request','meeting_reference':text,'evidence':text},courtesy=None)
            return Understanding.model_validate(payload)
    if not key or u.requires_clarification and not decline:return u
    if previous_meta.get('material_offer') or previous_meta.get('release_offer'):return u
    if not decline and not (_affirmative_slot_reply(text) and key=='reschedule_confirmation'):
        return u
    payload=u.model_dump(mode='json')
    payload.update(requests=[{'id':'reschedule_reply','topic':'appointment' if not decline else 'other','subject':None,'polarity':'request','evidence':text}],
        all_of=['reschedule_reply'],alternatives=[],requires_clarification=False,clarification_question=None,
        appointment_query=None,visit=None,reschedule={'action':'decline' if decline else 'confirm','evidence':text},courtesy=None)
    return Understanding.model_validate(payload)


def target_context(db,scope,project,property_id,unit_id,location,duration):
    row=Meeting(project_id=project.id,lead_id=scope.lead_id)
    bind_visit(db,row,company_id=scope.company_id,property_type_id=property_id,unit_id=unit_id)
    return {**row.visit_context,'location':location,'duration_minutes':duration}


def _approved_named(rows,value,key):
    matches=[r for r in rows if normalized(str(r[key]))==normalized(value)]
    if len(matches)!=1:raise ValueError('Please specify one approved property or unit by its exact name.')
    return matches[0]


def build_target(db,scope,conversation,old,directive,state,u,inbound):
    search=state.reschedule_search;project_id=search.get('target_project_id') or old.project_id
    if directive and directive.target_project:
        matches=db.query(Project).filter_by(company_id=scope.company_id).all()
        matches=[p for p in matches if normalized(p.name)==normalized(directive.target_project)]
        if len(matches)!=1:raise ValueError('Please specify one approved Project name for the visit change.')
        project_id=matches[0].id
    project,target_scope=authorize_target(db,scope,project_id)
    from .commercial_context import build_commercial_context
    catalog=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
    same_project=old.project_id==project_id
    property_id=search.get('property_type_id') if search.get('target_project_id')==project_id else old.visit_property_type_id if same_project else None
    unit_id=search.get('unit_id') if search.get('target_project_id')==project_id else old.visit_unit_id if same_project else None
    if directive and directive.target_property:
        property_id=_approved_named(catalog['property_types'],directive.target_property,'property_type')['id'];unit_id=None
    if directive and directive.target_unit:
        units=[r for r in catalog['inventory'] if r.get('unit_code')]
        unit=_approved_named(units,directive.target_unit,'unit_code');unit_id=unit['id']
        parents=[r for r in catalog['property_types'] if r['property_type']==unit.get('property_type')]
        property_id=parents[0]['id'] if len(parents)==1 else None
    state.reschedule_search={**search,'original_meeting_id':old.id,'target_project_id':project_id,'property_type_id':property_id,'unit_id':unit_id}
    if not property_id and not unit_id:
        if len(catalog['property_types'])==1:property_id=catalog['property_types'][0]['id']
        elif len(catalog['property_types'])>1:raise ValueError('Please name the property type for the replacement visit. Your original visit is unchanged.')
    location=resolve_visit_location(project,(directive.target_location if directive and directive.target_location else search.get('location') if search.get('target_project_id')==project_id else {'address':old.visit_address} if same_project else None))
    if not location:raise ValueError('Please name an approved visit location for the replacement. Your original visit is unchanged.')
    proxy=u.model_copy(update={'visit':VisitDirective(action='request',evidence=inbound.content,timing=directive.timing if directive else u.visit.timing if u.visit else None)})
    previous_preferences=dict(search.get('preferences') or {'duration_minutes':old.duration_minutes})
    if search.get('target_project_id')!=project_id and not previous_preferences.get('source_evidence',{}).get('timezone_evidence'):
        previous_preferences.pop('timezone',None)
    prefs=normalize_timing(proxy,inbound.content,project,datetime.utcnow(),previous_preferences)
    allowed=None
    if directive and directive.target_specialist:
        ids={r.user_id for r in eligible_appointment_assignments(db,project_id)}
        users=db.query(User).filter(User.id.in_(ids),User.company_id==scope.company_id,User.deleted_at.is_(None)).all()
        matches=[r for r in users if normalized(' '.join(v for v in [r.first_name,r.last_name] if v))==normalized(directive.target_specialist)]
        if len(matches)!=1:raise ValueError('Please specify an eligible specialist for that Project. Your original visit is unchanged.')
        allowed={matches[0].id}
    elif search.get('target_project_id')==project_id and search.get('allowed_user_ids'):allowed=set(search['allowed_user_ids'])
    context=target_context(db,scope,project,property_id,unit_id,location,prefs['duration_minutes'])
    state.reschedule_search={'original_meeting_id':old.id,'target_project_id':project_id,'property_type_id':property_id,'unit_id':unit_id,
        'location':location,'preferences':prefs,'allowed_user_ids':sorted(allowed) if allowed else [],'original_sha256':reservation_version(old)}
    return target_scope,context,prefs,allowed


def validate_prepared(db,scope,metadata):
    identifier=metadata.get('reschedule_operation_id')
    if not identifier:return
    op=db.query(SalesRescheduleOperation).filter_by(id=identifier,company_id=scope.company_id,lead_id=scope.lead_id).one()
    receipt=db.get(SalesBookingOperation,op.replacement_booking_operation_id)
    try:project,_=authorize_target(db,scope,receipt.project_id)
    except (PermissionError,HTTPException) as exc:raise ValueError('Replacement approval changed before commit.') from exc
    for model in (ProjectPropertyType,ProjectUnit):db.query(model).filter_by(project_id=project.id).populate_existing().all()
    context=receipt.snapshot_json['context']
    fresh=target_context(db,scope,project,context['property_type_id'],context['unit_id'],resolve_visit_location(project,context['location']),context['duration_minutes'])
    user=db.query(User).filter_by(id=receipt.snapshot_json['option']['sales_user_id'],company_id=scope.company_id,is_active=True,deleted_at=None).populate_existing().first()
    if fresh!=context or not user:raise ValueError('Replacement approval changed before commit.')


def replace_visit(db,scope,conversation,lead,outcome,inbound,proposal):
    now=datetime.utcnow();state=outcome.state
    from .first_booking import SalesBookingOperation as Booking
    # The F effect worker locks its receipt before its Meeting. Keep the same order.
    db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,project_id=scope.project_id).populate_existing().with_for_update().one()
    db.query(Booking).filter_by(meeting_id=proposal['original']['id']).with_for_update().all()
    old=db.query(Meeting).filter_by(id=proposal['original']['id'],lead_id=scope.lead_id).populate_existing().with_for_update().one_or_none()
    if not old or old.status not in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED} or old.meeting_time<=now or reservation_version(old)!=proposal['original']['booking_sha256']:
        state.reschedule_proposal=None
        return 'The original visit changed or is no longer eligible. Nothing else has been changed. Please review the current visit first.',{},[]
    project,target_scope=authorize_target(db,scope,proposal['target_context']['project_id'])
    context=proposal['target_context'];fresh=target_context(db,scope,project,context['property_type_id'],context['unit_id'],resolve_visit_location(project,context['location']),context['duration_minutes'])
    if fresh!=context or not fresh['location']:raise ValueError('The proposed visit details changed. Your original visit is unchanged.')
    option=proposal['option'];starts=datetime.fromisoformat(option['starts_at']).astimezone(timezone.utc).replace(tzinfo=None)
    if starts<=now:raise ValueError('The proposed time has passed. Your original visit is unchanged.')
    lock_ids={a.user_id for a in eligible_appointment_assignments(db,project.id)}|{old.assigned_sales_user_id}
    db.query(User).filter(User.id.in_([v for v in lock_ids if v])).order_by(User.id).populate_existing().with_for_update().all()
    user=db.query(User).filter_by(id=option['sales_user_id'],company_id=scope.company_id,deleted_at=None,is_active=True).first()
    if not user or ' '.join(v for v in [user.first_name,user.last_name] if v)!=option['specialist_name']:raise ValueError('The proposed specialist changed. Your original visit is unchanged.')
    if lead.deleted_at or lead.is_opt_out or lead.consent_status!='granted' or lead.agent_status=='human_control':raise PermissionError('Lead permissions changed before replacement.')
    from app.modules.sales_crm.scheduling import create_agent_appointment
    from app.modules.governance.services import enqueue_notification
    old_data=meeting_snapshot(db,old)
    old_connection=db.query(CalendarConnection).filter_by(user_id=old.assigned_sales_user_id,provider='google',status='connected').first()
    cleanup={'event_id':old.gcal_event_id,'user_id':old.assigned_sales_user_id,'connection_id':old_connection.id if old_connection else None,
        'calendar_id':old_connection.calendar_id if old_connection else None}
    # A savepoint preserves the original, routing cursor and lead on every failed replacement.
    try:
        with db.begin_nested():
            new,user=create_agent_appointment(db,lead=lead,starts_at=starts,duration_minutes=context['duration_minutes'],modality=old.modality,
                visit_location=context['location'],defer_calendar=True,visit_property_type_id=context['property_type_id'],visit_unit_id=context['unit_id'],
                capture_visit_context=True,required_sales_user_id=option['sales_user_id'],excluded_meeting=old,booking_project_id=project.id,emit_notification=False)
            new.source='agent_next_rescheduled'
            saved={'context':{**new.visit_context,'location':{'label':new.visit_location_label,'address':new.visit_address},'duration_minutes':new.duration_minutes},
                'option':{**option,'starts_at':utc(new.meeting_time).isoformat()},'preferences':proposal['preferences']}
            receipt=SalesBookingOperation(company_id=scope.company_id,project_id=project.id,conversation_id=scope.conversation_id,lead_id=lead.id,
                proposal_id=proposal['id'],meeting_id=new.id,snapshot_json=saved,calendar_status='simulation' if new.is_demo else 'pending',next_attempt_at=now)
            db.add(receipt);db.flush()
            operation=SalesRescheduleOperation(company_id=scope.company_id,project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=lead.id,
                proposal_id=proposal['id'],original_meeting_id=old.id,replacement_meeting_id=new.id,replacement_booking_operation_id=receipt.id,
                snapshot_json={'original':old_data,'replacement':saved,'cleanup':cleanup},calendar_status='simulation' if new.is_demo else 'pending',next_attempt_at=now)
            db.add(operation);db.flush()
            old.status=MeetingStatus.CANCELLED;old.confirmation_status='rescheduled'
            previous=db.query(Booking).filter_by(meeting_id=old.id).first()
            if previous:previous.calendar_status='cancelled'
            for kind,uid,pid in [('previous',old.assigned_sales_user_id,old.project_id),('replacement',new.assigned_sales_user_id,new.project_id)]:
                if uid:enqueue_notification(db,company_id=scope.company_id,project_id=pid,event_type='appointment_rescheduled',entity_type='lead',entity_id=lead.id,
                    payload={'assigned_sales_user_id':uid,'recipient_user_ids':[uid],'title':'Appointment rescheduled',
                        'body':f"Previous visit: {current_description(old_data)}. Replacement: {current_description({**meeting_snapshot(db,new)})}.",
                        'action_url':'/app/schedule'},dedupe_key=f'reschedule:{operation.id}:{kind}')
            db.flush()
    except HTTPException as exc:
        if exc.status_code!=409:raise
        state.reschedule_proposal=None
        return 'The replacement time is no longer available. Your original reservation is unchanged. Would you like other options?',{},[]
    state.reschedule_proposal=None;state.reschedule_search={}
    stop_cadence(db,conversation,lead,state,'booked')
    conversation.stage='appointment_confirmed';lead.pipeline_stage='S09_HANDOFF';lead.agent_status='appointment_confirmed'
    return comparison({**proposal,'target_context':saved['context'],'option':saved['option']},confirmed=True),{
        'meeting_id':new.id,'booking_operation_id':receipt.id,'reschedule_operation_id':operation.id,'post_booking_question':True},[
        {'type':'appointment_rescheduled','original_meeting_id':old.id,'meeting_id':new.id,'operation_id':operation.id}]


def handle(db,scope,conversation,lead,project,outcome,inbound,previous_meta):
    state=outcome.state;u=state.last_understanding;directive=directive_for(u);now=datetime.utcnow()
    if u.requires_clarification or u.confidence<.8:return 'Please clarify which visit you want to change. Your current reservation is unchanged.',{},[]
    if directive and directive.action=='decline':
        state.reschedule_proposal=None;state.reschedule_search={}
        return 'I have kept your original reservation. You can continue asking questions.',{'reschedule_declined':True},[]
    if not u.permits('appointment') or u.appointment_query:return '',{},[]
    if not any(t.source_message_id==inbound.id and t.topic.value=='appointment' and t.id in outcome.plan.get('write_candidates_require_backend_authorization',[]) for t in state.tasks):return '',{},[]
    proposal=state.reschedule_proposal
    from .service import _affirmative_slot_reply
    assent=_affirmative_slot_reply(inbound.content)
    if directive and directive.action=='confirm':
        from app.modules.governance.services import request_attribution
        assent|=_affirmative_slot_reply(directive.evidence) and request_attribution(inbound.content)['current_text'].lstrip().startswith(directive.evidence)
    prompt=accepted_outbound(db,conversation,'reschedule_confirmation')
    if assent and proposal and prompt and (prompt.metadata_json or {}).get('reschedule_confirmation',{}).get('id')==proposal['id']:
        if proposal.get('id')!=digest({k:v for k,v in proposal.items() if k!='id'}) or proposal['scope']!=scope.__dict__:
            state.reschedule_proposal=None
            return 'The replacement proposal changed. Your original reservation is unchanged. Please request a new comparison.',{},[]
        if datetime.fromisoformat(proposal['expires_at'])<=utc(now):
            state.reschedule_proposal=None
            return 'The replacement proposal expired. Your original reservation is unchanged. Please request current options.',{},[]
        try:return replace_visit(db,scope,conversation,lead,outcome,inbound,proposal)
        except (PermissionError,ValueError) as exc:
            state.reschedule_proposal=None
            return str(exc) if isinstance(exc,ValueError) else 'The replacement needs access or approval review. Your original reservation is unchanged.',{},[]
    if assent:return 'Please review a current replacement comparison before confirming. Your original visit is unchanged.',{},[]
    refs=[r['value'] for r in outcome.plan.get('references',{}).values() if r.get('status')=='resolved' and r.get('value',{}).get('kind')=='appointment']
    offered=accepted_outbound(db,conversation,'reschedule_offer');offer=(offered.metadata_json or {}).get('reschedule_offer') if offered else None
    if not offered and refs:
        from .conversation_scope import scoped_messages_query
        from .models import SalesMessage
        for ref in refs:
            row=scoped_messages_query(db,conversation).filter_by(id=ref.get('message_id')).first()
            if row and accepted_outbound(db,conversation,'reschedule_offer',message=row):offered=row;offer=row.metadata_json['reschedule_offer'];break
    selected=next((o for o in (offer or {}).get('options',[]) if any(r['id']==o['starts_at'] for r in refs)),None)
    if selected and offer:
        if offer['scope']!=scope.__dict__ or offer['id']!=digest({k:v for k,v in offer.items() if k!='id'}) or datetime.fromisoformat(offer['expires_at'])<=utc(now):
            return 'Those replacement options expired or changed. Your original reservation is unchanged.',{},[]
        proposal={k:v for k,v in offer.items() if k not in {'id','options'}}
        proposal.update(option=selected,offer_message_id=offered.id)
        proposal['id']=digest(proposal);state.reschedule_proposal=proposal
        return comparison(proposal),{'reschedule_confirmation':{'id':proposal['id'],'expires_at':proposal['expires_at']}},[]
    old,rows=resolve_original(db,scope,conversation,directive,state)
    if old is None:
        if not rows:return 'I could not find a future active visit eligible for this change. No reservation has been changed.',{},[]
        return 'Which current visit would you like to change?\n\n'+'\n\n'.join(f'{i}. {current_description(meeting_snapshot(db,r))}' for i,r in enumerate(rows,1)),{'reschedule_meeting_offer':{'meeting_ids':[r.id for r in rows]}},[]
    try:
        authorize_target(db,scope,old.project_id)
        target_scope,context,prefs,allowed=build_target(db,scope,conversation,old,directive,state,u,inbound)
        options=search_slots(db,target_scope,prefs,now,excluded_meeting=old,allowed_user_ids=allowed)
    except (PermissionError,ValueError,HTTPException):
        return 'Please verify an approved Project, property, location, specialist and time for the replacement. Your original reservation is unchanged.',{'reschedule_context_question':True},[]
    original=meeting_snapshot(db,old)
    options=[o for o in options if not (o['starts_at']==original['starts_at'] and o['sales_user_id']==original['sales_user_id'] and
        context['project_id']==original['project_id'] and context['property_type_id']==original['property_type_id'] and
        context['unit_id']==original['unit_id'] and context['location']['address']==original['location']['address'] and context['duration_minutes']==original['duration_minutes'])]
    if not options:return 'I found no verified replacement in the checked range. Your original reservation is unchanged. Would you like a different date or time?',{'reschedule_context_question':True},[]
    offer={'version':VERSION,'scope':scope.__dict__,'original':original,'target_context':context,'preferences':prefs,'options':options,
        'expires_at':(utc(now)+timedelta(minutes=30)).isoformat()}
    offer['id']=digest(offer)
    appointment={'version':VERSION,'slots':[o['starts_at'] for o in options],'options':options,'duration_minutes':prefs['duration_minutes'],'project_timezone':prefs['timezone']}
    state.reschedule_proposal=None
    return 'Your current reservation is unchanged. Verified replacement options:\n\n'+'\n\n'.join(f'{i}. {label(o,prefs)}' for i,o in enumerate(options,1))+'\n\nWhich option should I compare with your current visit?',{'reschedule_offer':offer,'appointment_offer':appointment},[{'type':'request_reschedule_options'}]


def advance_effect(db,operation_id):
    """Create the new event first. Retire only the exact former event after success."""
    op=db.get(SalesRescheduleOperation,operation_id)
    if not op or op.calendar_status in {'completed','review','simulation','cancelled'}:return
    if op.calendar_status!='pending' and op.next_attempt_at>datetime.utcnow():return
    new_receipt=db.get(SalesBookingOperation,op.replacement_booking_operation_id)
    seen=set()
    while new_receipt.calendar_status=='cancelled':
        if new_receipt.id in seen or len(seen)>=10:
            op.calendar_status='review';op.last_error='ReplacementChainLimit';db.commit();return
        seen.add(new_receipt.id)
        next_op=db.query(SalesRescheduleOperation).filter_by(original_meeting_id=new_receipt.meeting_id,company_id=op.company_id,lead_id=op.lead_id).first()
        if not next_op:
            op.calendar_status='review';op.last_error='ReplacementNoLongerActive';db.commit();return
        new_receipt=db.get(SalesBookingOperation,next_op.replacement_booking_operation_id)
    effective_receipt_id=new_receipt.id
    from .next_flow import selected
    from .active_service import selected_policy
    source_scope=Scope(op.company_id,op.project_id,op.conversation_id,op.lead_id)
    if not selected(source_scope) or not selected_policy(db,source_scope) or not selected(replace(source_scope,project_id=new_receipt.project_id)) or not selected_policy(db,replace(source_scope,project_id=new_receipt.project_id)):return
    if new_receipt.calendar_status not in {'synced','simulation','review'} and new_receipt.next_attempt_at<=datetime.utcnow():
        from .first_booking import sync_calendar
        sync_calendar(db,new_receipt.id)
    op=db.query(SalesRescheduleOperation).filter_by(id=operation_id).populate_existing().with_for_update(skip_locked=True).first()
    if not op or op.calendar_status in {'completed','review','simulation','cancelled'}:return
    new_receipt=db.query(SalesBookingOperation).filter_by(id=effective_receipt_id).populate_existing().one()
    cleanup=op.snapshot_json['cleanup']
    if new_receipt.calendar_status not in {'synced','simulation'}:
        op.calendar_status='review' if new_receipt.calendar_status=='review' else 'waiting_new_calendar'
        op.last_error='NewCalendarNeedsReview' if op.calendar_status=='review' else None
        op.next_attempt_at=datetime.utcnow()+timedelta(minutes=5);db.commit();return
    if not cleanup.get('event_id'):
        op.calendar_status='completed';op.last_error=None;db.commit();return
    old=db.query(Meeting).filter_by(id=op.original_meeting_id,lead_id=op.lead_id).with_for_update().first()
    if not old or old.gcal_event_id!=cleanup['event_id'] or old.status!=MeetingStatus.CANCELLED or old.confirmation_status!='rescheduled':
        op.calendar_status='review';op.last_error='OriginalCalendarBindingChanged';db.commit();return
    connection=db.query(CalendarConnection).filter_by(id=cleanup.get('connection_id'),user_id=cleanup['user_id'],provider='google').first()
    owner=db.query(User).filter_by(id=cleanup['user_id'],company_id=op.company_id,deleted_at=None).first()
    if not connection or not owner or connection.calendar_id!=cleanup.get('calendar_id'):
        op.calendar_status='review';op.last_error='OriginalCalendarConnectionChanged';db.commit();return
    if connection.status!='connected':
        op.calendar_status='waiting_old_connection';op.next_attempt_at=datetime.utcnow()+timedelta(minutes=10);db.commit();return
    from app.integrations.gcalendar_client import delete_calendar_event_for_connection
    op.attempts+=1
    try:
        delete_calendar_event_for_connection(db,connection,cleanup['event_id'])
        old.calendar_sync_status='rescheduled_removed';op.calendar_status='completed';op.last_error=None
    except Exception as exc:
        op.calendar_status='review' if op.attempts>=5 else 'retry';op.last_error=type(exc).__name__
        op.next_attempt_at=datetime.utcnow()+timedelta(minutes=min(60,2**op.attempts))
    db.commit()


def advance_for_meeting(db,scope,meeting_id):
    row=db.query(SalesRescheduleOperation).filter_by(company_id=scope.company_id,lead_id=scope.lead_id,replacement_meeting_id=meeting_id).first()
    if row:advance_effect(db,row.id)


def retry_effects(db,limit=10):
    from app.core.config import settings
    from app.modules.ai_core.models import AIConfiguration
    from .runtime_policy import RuntimePolicy
    from .next_flow import selected
    from .active_service import selected_policy
    from uuid import UUID
    if not settings.SALES_DIALOGUE_RUNTIME_ENABLED or not settings.SALES_NEXT_FLOW_ENABLED:return
    ids=[v.strip() for v in settings.SALES_NEXT_FLOW_PROJECT_IDS.split(',') if v.strip()]
    try:
        if not ids or any(str(UUID(v))!=v for v in ids):return
    except ValueError:return
    config=db.query(AIConfiguration).filter_by(company_id=None).first()
    policy=RuntimePolicy.model_validate((config.agent_ventas or {}).get('runtime_config') or {}) if config else RuntimePolicy()
    if policy.mode!='active':return
    query=db.query(SalesRescheduleOperation).join(SalesBookingOperation,SalesBookingOperation.id==SalesRescheduleOperation.replacement_booking_operation_id).filter(
        SalesRescheduleOperation.calendar_status.in_(['pending','retry','waiting_new_calendar','waiting_old_connection']),
        SalesRescheduleOperation.next_attempt_at<=datetime.utcnow(),SalesRescheduleOperation.project_id.in_(ids),SalesBookingOperation.project_id.in_(ids))
    if policy.scope=='cohort':
        query=query.filter(SalesRescheduleOperation.company_id.in_(policy.company_ids),SalesRescheduleOperation.project_id.in_(policy.project_ids),SalesBookingOperation.project_id.in_(policy.project_ids))
        if policy.lead_ids:query=query.filter(SalesRescheduleOperation.lead_id.in_(policy.lead_ids))
    for row in query.order_by(SalesRescheduleOperation.next_attempt_at).limit(limit).all():
        scope=Scope(row.company_id,row.project_id,row.conversation_id,row.lead_id)
        receipt=db.get(SalesBookingOperation,row.replacement_booking_operation_id)
        if selected(scope) and selected_policy(db,scope) and selected(replace(scope,project_id=receipt.project_id)):
            advance_effect(db,row.id)
