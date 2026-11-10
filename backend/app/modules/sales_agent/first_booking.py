from .execution import now as workflow_now
from .execution import permitted
"""First visit: evidence-based preferences, exact confirmation, durable effect receipt."""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from fastapi import HTTPException
from app.modules.projects.models import Project, ProjectPropertyType
from app.modules.projects.locations import locations_for_project, resolve_visit_location
from app.modules.sales_crm.models import Lead, Meeting, MeetingStatus, CalendarConnection
from app.modules.users.models import User
from app.modules.project_team.models import ProjectRoutingState
from app.modules.project_team.service import eligible_appointment_assignments
from .booking_models import SalesBookingOperation
from .dialogue_store import check_scope
from .dialogue_tasks import restricted
from .turn_configuration import digest
from .appointment_context import ACTIVE, utc, bind_visit

VERSION='sales-first-booking/1.0'
ACCEPTED={'sent','delivered','read','accepted'}


def active_meetings(db,scope,now=None):
    now=now or workflow_now(datetime)
    rows=db.query(Meeting).join(Project,Project.id==Meeting.project_id).filter(
        Meeting.lead_id==scope.lead_id,Project.company_id==scope.company_id,Meeting.status.in_(list(ACTIVE))).all()
    from .execution import simulated
    return [r for r in rows if bool(r.is_demo) == simulated(scope) and r.meeting_time+timedelta(minutes=r.duration_minutes)>now]


def stop_cadence(db,conversation,lead,state,reason):
    from .models import SalesFollowUpJob
    state.cadence_status='stopped';state.cadence_stop_reason=reason
    lead.next_action_at=None
    jobs=db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id).filter(SalesFollowUpJob.status.in_(['pending','processing'])).all()
    for job in jobs:
        if job.reason.endswith('_cadence'):job.status='cancelled'


def recover_booking_pause(db,conversation):
    """Only the legacy system booking pause is recoverable, never human control or opt-out."""
    if not conversation.is_paused or conversation.pause_reason!='Appointment confirmed':return False
    from .next_flow import selected
    from .active_service import selected_policy
    from .dialogue_store import Scope,load,save
    from app.modules.governance.models import HumanInterventionCase
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    if not selected(scope) or not selected_policy(db,scope):return False
    check_scope(db,scope)
    lead=db.get(Lead,scope.lead_id)
    if not lead or lead.deleted_at or lead.is_opt_out or not permitted(lead) or lead.agent_status=='human_control':return False
    if db.query(HumanInterventionCase).filter_by(conversation_id=conversation.id,status='open').first():return False
    if not db.query(Meeting).filter_by(project_id=scope.project_id,lead_id=scope.lead_id,is_demo=conversation.channel == 'simulation').first():return False
    revision,state=load(db,scope)
    stop_cadence(db,conversation,lead,state,'booked')
    conversation.is_paused=False;conversation.pause_reason=None
    save(db,scope,event_key='booking-continuity:'+str(revision+1),expected_revision=revision,state=state,
        metadata={'reason':'legacy_system_booking_pause','human_control_lifted':False,'reservation_changed':False})
    return True


def cadence_stopped(db,conversation):
    from .next_flow import selected
    if not selected(conversation):return False
    from .dialogue_store import Scope,load
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    return load(db,scope)[1].cadence_status=='stopped' or bool(active_meetings(db,scope))


def accepted_outbound(db,conversation,key,*,message=None):
    from .turn_context import latest_outbound
    from .reference_resolution import accepted
    from .conversation_scope import scoped_messages_query
    row=message or latest_outbound(db,conversation.id,skip_language_holds=True)
    if not row or not accepted(row) or not (row.metadata_json or {}).get(key):return None
    group=(row.metadata_json or {}).get('delivery_group') or {}
    if group.get('total',1)>1:
        parts=scoped_messages_query(db,conversation).filter_by(direction='outbound').all()
        indexes={((p.metadata_json or {}).get('delivery_group') or {}).get('part') for p in parts
            if ((p.metadata_json or {}).get('delivery_group') or {}).get('key')==group.get('key') and accepted(p)}
        if indexes!=set(range(1,group['total']+1)):return None
    return row


def normalize_timing(u,text,project,now,previous):
    """Normalize only temporal evidence after semantic appointment interpretation."""
    from .service import _requested_period,_selected_time
    timing=u.visit.timing if u.visit else None
    supplied=timing.model_dump() if timing else {}
    zone_name=supplied.get('timezone_evidence') or previous.get('timezone') or project.timezone or 'UTC'
    try:zone=ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError,ValueError):raise ValueError('Please specify a valid IANA timezone, such as America/Chicago.')
    def period(evidence):
        if not evidence:return None
        result=_requested_period(evidence,now=now,zone=zone)
        if not result:raise ValueError('Please specify the preferred visit date or date range.')
        return result
    date_evidence=supplied.get('date_from_evidence')
    date_end_evidence=supplied.get('date_until_evidence')
    dates=period(date_evidence) if date_evidence else _requested_period(text,now=now,zone=zone)
    end_dates=period(date_end_evidence)
    start=dates[0].isoformat() if dates else previous.get('date_from')
    end=(end_dates or dates)[1].isoformat() if end_dates or dates else previous.get('date_until')
    if start and end and end<start:raise ValueError('The last date must be on or after the first date.')
    def clock(value):
        if not value:return None
        result=_selected_time(value)
        if result is None:
            try:result=time.fromisoformat(value)
            except ValueError:raise ValueError('Please specify the preferred local time, including AM or PM.')
        return result.strftime('%H:%M')
    relation=supplied.get('time_relation') or previous.get('time_relation','any')
    if timing and relation in {'after','before','morning','afternoon','evening'} and not re.search(r'\b'+relation+r'\b',text,re.I):
        raise ValueError('Please clarify your preferred time of day or time range.')
    lower=clock(supplied.get('time_from_evidence')) or previous.get('time_from')
    upper=clock(supplied.get('time_until_evidence')) or previous.get('time_until')
    if not timing and _selected_time(text):lower=_selected_time(text).strftime('%H:%M');relation='exact'
    if relation=='morning':lower,upper='06:00','12:00'
    elif relation=='afternoon':lower,upper='12:00','18:00'
    elif relation=='evening':lower,upper='18:00','22:00'
    if relation in {'exact','after','before','range'} and not lower:raise ValueError('Please specify the preferred local time, including AM or PM.')
    if relation=='range' and (not upper or upper<=lower):raise ValueError('Please specify a local time range whose end is after its start.')
    duration=previous.get('duration_minutes',45)
    if supplied.get('duration_evidence'):
        match=re.fullmatch(r'\s*(\d{1,3})\s*(?:minutes?|mins?)\s*',supplied['duration_evidence'],re.I)
        if not match or not 15<=int(match[1])<=180:raise ValueError('Please request a visit duration between 15 and 180 minutes.')
        duration=int(match[1])
    return {'timezone':zone_name,'date_from':start,'date_until':end,'time_relation':relation,
        'time_from':lower,'time_until':upper,'duration_minutes':duration,
        'source_evidence':{k:v for k,v in supplied.items() if k!='time_relation' and v},'source':'current_message_or_saved_explicit_preferences'}


def context_snapshot(db,scope,project,state,location):
    temp=Meeting(project_id=project.id,lead_id=scope.lead_id)
    bind_visit(db,temp,company_id=scope.company_id,property_type_id=state.booking_search.get('property_type_id'),unit_id=state.booking_search.get('unit_id'))
    return {**temp.visit_context,'location':location,'duration_minutes':state.booking_search['duration_minutes']}


def choose_user(db,project_id,ids):
    assignments=eligible_appointment_assignments(db,project_id)
    values=[r.user_id for r in assignments if r.user_id in ids]
    cursor=db.query(ProjectRoutingState).filter_by(project_id=project_id).first()
    last=cursor.last_assigned_user_id if cursor else None
    return values[(values.index(last)+1)%len(values)] if last in values else values[0] if values else None


def search_slots(db,scope,prefs,now,*,excluded_meeting=None,allowed_user_ids=None):
    from datetime import date
    from app.modules.sales_crm.scheduling import available_slots,eligible_users_for_slot
    if not eligible_appointment_assignments(db,scope.project_id):return []
    zone=ZoneInfo(prefs['timezone']);today=utc(now).astimezone(zone).date()
    first=date.fromisoformat(prefs['date_from']) if prefs.get('date_from') else today
    last=date.fromisoformat(prefs['date_until']) if prefs.get('date_until') else first+timedelta(days=13)
    if last<today:return []
    if first>today+timedelta(days=90) or (last-first).days>30:raise ValueError('Please choose a visit range within 90 days and no longer than 31 days.')
    first=max(first,today);result=[]
    last=min(last,first+timedelta(days=13))
    def matches(starts,ends):
        local_start=utc(starts).astimezone(zone);local_end=utc(ends).astimezone(zone)
        if starts<=now or not first<=local_start.date()<=last:return False
        value=local_start.strftime('%H:%M');endvalue=local_end.strftime('%H:%M');kind=prefs['time_relation']
        lower,upper=prefs.get('time_from'),prefs.get('time_until')
        if kind=='exact' and value!=lower or kind=='after' and value<lower or kind=='before' and value>=lower:return False
        if kind in {'range','morning','afternoon','evening'} and (value<lower or local_end.date()!=local_start.date() or endvalue>upper):return False
        return True
    local=datetime.combine(first,time.min,tzinfo=zone)
    after=max(now,local.astimezone(timezone.utc).replace(tzinfo=None)-timedelta(microseconds=1))
    # One availability scan and one FreeBusy range per connected specialist.
    # One extra UTC day covers local daylight-saving offsets; the predicate clips the range.
    slots=available_slots(db,project_id=scope.project_id,after=after,duration_minutes=prefs['duration_minutes'],
        days=(last-first).days+2,limit=3,slot_predicate=matches,include_sales_user_ids=True,
        **({'allowed_sales_user_ids':allowed_user_ids} if allowed_user_ids is not None else {}),
        **({'excluded_meeting':excluded_meeting} if excluded_meeting else {}))
    for slot in slots:
        starts=slot['start_at']
        ids=slot.get('eligible_sales_user_ids')
        if ids is None:ids=eligible_users_for_slot(db,project_id=scope.project_id,starts_at=starts,duration_minutes=prefs['duration_minutes'])
        if allowed_user_ids is not None:ids=[uid for uid in ids if uid in allowed_user_ids]
        user_id=choose_user(db,scope.project_id,ids)
        user=db.query(User).filter_by(id=user_id,company_id=scope.company_id,deleted_at=None).first() if user_id else None
        if user:result.append({'starts_at':utc(starts).isoformat(),'sales_user_id':user.id,
            'specialist_name':' '.join(v for v in [user.first_name,user.last_name] if v) or 'Sales specialist'})
    return result[:3]


def label(option,prefs):
    value=datetime.fromisoformat(option['starts_at']).astimezone(ZoneInfo(prefs['timezone']))
    return value.strftime('%Y-%m-%d at %I:%M %p')+f" ({prefs['timezone']}, UTC{value.strftime('%z')}); {option['specialist_name']}"


def exact_public_selection(text, offer):
    """Recover only a complete backend-rendered option explicitly chosen now.

    No bare date, ordinal, quotation or affirmation is sufficient. This prepares
    a proposal only; expiry, scope, availability and confirmation remain mandatory.
    """
    if not offer or offer.get('version')!=VERSION:return None
    for index,option in enumerate(offer.get('options',[])):
        ordinal=('first','second','third')[index] if index<3 else str(index+1)
        rendered=label(option,offer['preferences'])
        pattern=(r"(?:The first time does not work for me\. )?"
                 r"(?:I would like|I'd like|I choose|I'll take) the "+ordinal+
                 r" appointment: "+re.escape(rendered)+r"\.?")
        if re.fullmatch(pattern,text,re.I):
            return {'kind':'appointment','id':option['starts_at']}
    return None


def confirmation(snapshot,option,prefs,*,booked=False):
    property_name=snapshot.get('property_type_name') or snapshot.get('project_name')
    if snapshot.get('unit_code'):property_name+=' / unit '+snapshot['unit_code']
    prefix='Your visit is confirmed' if booked else 'Please confirm your visit'
    text=f"{prefix}: {property_name}; {label(option,prefs)}; {prefs['duration_minutes']} minutes; {snapshot['location']['label']}: {snapshot['location']['address']}."
    return text+(' What else would you like to know before your visit?' if booked else ' Shall I book this exact visit?')


def handle(db,scope,conversation,lead,project,outcome,inbound):
    from .service import _affirmative_slot_reply
    from .turn_context import choice_index,latest_outbound
    state=outcome.state;u=state.last_understanding;now=workflow_now(datetime)
    if u.appointment_query:return None  # Existing scoped reader remains authoritative.
    if u.visit and u.visit.action=='decline' and not u.requires_clarification and u.confidence>=.8:
        state.booking_proposal=None;stop_cadence(db,conversation,lead,state,'cancelled' if state.cadence_stop_reason=='cancelled' else 'declined')
        message='Your existing visit is unchanged. You can continue asking about the property.' if active_meetings(db,scope,now) else 'No visit has been booked. You can continue asking about the property.'
        return message,{'booking_declined':True},[]
    if not u.permits('appointment') or u.confidence<.8:return '',{},[]
    candidates={t.id for t in state.tasks if t.source_message_id==inbound.id and t.topic.value=='appointment' and not restricted(state,t)}
    if not candidates & set(outcome.plan.get('write_candidates_require_backend_authorization',[])):return '',{},[]
    from app.modules.onboarding_versions import require_capability
    from .execution import simulated
    if project.profile and not (simulated(scope) and project.is_demo):require_capability(project.profile,'appointments')
    existing=active_meetings(db,scope,now)
    if existing:
        stop_cadence(db,conversation,lead,state,'booked')
        return 'You already have an active visit. I can help review its details. A change requires a separate confirmed request.',{'existing_meeting_ids':[r.id for r in existing]},[]
    if u.visit and u.visit.action in {'reschedule','cancel'}:
        return 'I have not changed any appointment. Please specify the appointment you want to review.',{},[]
    if u.visit and u.visit.action=='decline':
        state.booking_proposal=None;stop_cadence(db,conversation,lead,state,'cancelled' if state.cadence_stop_reason=='cancelled' else 'declined')
        return 'No visit has been booked. You can continue asking about the property.',{'booking_declined':True},[]
    proposal=state.booking_proposal
    prompt=accepted_outbound(db,conversation,'booking_confirmation')
    assent=_affirmative_slot_reply(inbound.content)
    if not assent and u.visit and u.visit.action=='confirm':
        from app.modules.governance.services import request_attribution
        own=request_attribution(inbound.content)['current_text'].lstrip()
        assent=_affirmative_slot_reply(u.visit.evidence) and own.startswith(u.visit.evidence)
    if assent and proposal and prompt and (prompt.metadata_json or {}).get('booking_confirmation',{}).get('id')==proposal['id']:
        if proposal.get('id')!=digest({k:v for k,v in proposal.items() if k!='id'}):
            state.booking_proposal=None
            return 'The visit proposal changed. Please request current visit options before confirming.',{},[]
        if datetime.fromisoformat(proposal['expires_at'])<=utc(now):
            state.booking_proposal=None
            return 'That visit proposal expired. Please request current visit times.',{},[]
        if proposal['scope']!=scope.__dict__:raise PermissionError('Booking proposal belongs to another opportunity.')
        # Serialize separate conversations/channels for this lead before checking active visits.
        locked_lead=db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id).populate_existing().with_for_update().one()
        if locked_lead.deleted_at or locked_lead.is_opt_out or not permitted(locked_lead) or locked_lead.agent_status=='human_control':
            raise PermissionError('Lead permissions changed before booking.')
        prior=db.query(SalesBookingOperation).filter_by(proposal_id=proposal['id']).first()
        if prior:
            return confirmation(prior.snapshot_json['context'],prior.snapshot_json['option'],prior.snapshot_json['preferences'],booked=True),{'meeting_id':prior.meeting_id,'booking_operation_id':prior.id},[]
        if active_meetings(db,scope,now):return 'You already have an active visit. Would you like to review its details?',{},[]
        try:fresh=context_snapshot(db,scope,project,state,resolve_visit_location(project,proposal['context']['location']))
        except (PermissionError,ValueError):
            state.booking_proposal=None
            return 'The approved property details changed. Please request current visit options before confirming.',{},[]
        if fresh!=proposal['context'] or not fresh['location']:
            state.booking_proposal=None
            return 'The visit details changed. Please request current visit options before confirming.',{},[]
        from app.modules.sales_crm.scheduling import create_agent_appointment
        option=proposal['option'];starts=datetime.fromisoformat(option['starts_at']).astimezone(timezone.utc).replace(tzinfo=None)
        if starts<=now:return 'That visit time has passed. Please request current visit options.',{},[]
        user=db.query(User).filter_by(id=option['sales_user_id'],company_id=scope.company_id,deleted_at=None,is_active=True).one_or_none()
        if not user or ' '.join(v for v in [user.first_name,user.last_name] if v)!=option['specialist_name']:
            state.booking_proposal=None
            return 'The specialist details changed. Please request current visit options.',{},[]
        try:
            meeting,user=create_agent_appointment(db,lead=lead,starts_at=starts,duration_minutes=proposal['preferences']['duration_minutes'],
                modality='showroom',visit_location=fresh['location'],defer_calendar=True,
                visit_property_type_id=fresh['property_type_id'],visit_unit_id=fresh['unit_id'],capture_visit_context=True,
                required_sales_user_id=option['sales_user_id'])
        except HTTPException as exc:
            if exc.status_code!=409:raise
            state.booking_proposal=None
            return 'That visit is no longer available. Nothing was booked. Would you like me to check current times?',{},[]
        meeting.source='agent_next_first_booking'
        saved={'context':{**meeting.visit_context,'location':{'label':meeting.visit_location_label,'address':meeting.visit_address},'duration_minutes':meeting.duration_minutes},
               'option':{**option,'starts_at':utc(meeting.meeting_time).isoformat()},'preferences':proposal['preferences']}
        op=SalesBookingOperation(company_id=scope.company_id,project_id=scope.project_id,conversation_id=scope.conversation_id,
            lead_id=scope.lead_id,proposal_id=proposal['id'],meeting_id=meeting.id,snapshot_json=saved,
            calendar_status='simulation' if meeting.is_demo else 'pending',next_attempt_at=now)
        db.add(op);db.flush()
        conversation.stage='appointment_confirmed';conversation.is_paused=False;conversation.pause_reason=None
        lead.pipeline_stage='S09_HANDOFF';lead.agent_status='appointment_confirmed'
        stop_cadence(db,conversation,lead,state,'booked');state.booking_proposal=None
        return confirmation(saved['context'],saved['option'],saved['preferences'],booked=True),{'meeting_id':meeting.id,'booking_operation_id':op.id,'post_booking_question':True},[{'type':'appointment_confirmed','meeting_id':meeting.id,'operation_id':op.id}]
    # A time selection only prepares a full immutable proposal; never books directly.
    refs=[r['value'] for r in outcome.plan.get('references',{}).values() if r.get('status')=='resolved' and r.get('value',{}).get('kind')=='appointment']
    offered=accepted_outbound(db,conversation,'appointment_offer')
    offer=(offered.metadata_json or {}).get('appointment_offer') if offered else None
    chosen=next((r for r in refs if offer and any(o['starts_at']==r['id'] for o in offer.get('options',[]))),None)
    if not chosen:
        from .conversation_scope import scoped_messages_query
        from .models import SalesMessage
        # Explicit temporal references may resume a still-valid suspended offer.
        # The resolver has already rejected bare property ordinals as slot consent.
        for value in refs:
            if not value.get('message_id'):continue
            row=scoped_messages_query(db,conversation).filter_by(id=value['message_id']).first()
            row=accepted_outbound(db,conversation,'appointment_offer',message=row) if row else None
            previous_offer=(row.metadata_json or {}).get('appointment_offer') if row else None
            if previous_offer and any(o['starts_at']==value['id'] for o in previous_offer.get('options',[])):
                offered,offer,chosen=row,previous_offer,value;break
    if not chosen:
        chosen=exact_public_selection(inbound.content,offer)
    if chosen and offer.get('version')==VERSION:
        if datetime.fromisoformat(offer['expires_at'])<=utc(now):return 'Those visit times expired. Please request current options.',{},[]
        option=next(o for o in offer['options'] if o['starts_at']==chosen['id'])
        state.booking_search={**offer['preferences'],'property_type_id':offer['context']['property_type_id'],'unit_id':offer['context']['unit_id'],'location':offer['context']['location']}
        proposal={'scope':scope.__dict__,'context':offer['context'],'option':option,'preferences':offer['preferences'],
            'offer_message_id':offered.id,'expires_at':offer['expires_at']}
        proposal['id']=digest(proposal);state.booking_proposal=proposal
        return confirmation(proposal['context'],option,proposal['preferences']),{'booking_confirmation':{'id':proposal['id'],'expires_at':proposal['expires_at']}},[]
    if assent:
        return 'Please choose a current visit time before confirming a booking.',{},[]
    previous=state.booking_search
    try:prefs=normalize_timing(u,inbound.content,project,now,previous)
    except ValueError as exc:return str(exc),{},[]
    property_id=state.selected_property_type_id or previous.get('property_type_id')
    unit_id=state.selected_unit_id if state.selected_unit_id else previous.get('unit_id') if property_id==previous.get('property_type_id') else None
    from .commercial_context import build_commercial_context
    catalog=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
    if not property_id and not unit_id:
        types=catalog['property_types']
        if len(types)==1:property_id=types[0]['id']
        elif len(types)>1:
            state.booking_search={**previous,**prefs}
            return 'Which property would you like to visit?\n\n'+'\n'.join(f"{i}. {r['property_type']}" for i,r in enumerate(types,1)),{'booking_property_question':True,'property_catalog_offer':{'property_type_ids':[r['id'] for r in types]}},[]
    location=resolve_visit_location(project,previous.get('location'))
    refs_locations=[r['value']['id'] for r in outcome.plan.get('references',{}).values() if r.get('status')=='resolved' and r.get('value',{}).get('kind')=='location']
    if refs_locations:location=resolve_visit_location(project,refs_locations[0])
    state.booking_search={**prefs,'property_type_id':property_id,'unit_id':unit_id,'location':location}
    state.booking_proposal=None
    if not location:
        locations=locations_for_project(project)
        if not locations:return 'A visit location needs to be approved before I can offer times. What property information would help meanwhile?',{},[]
        return 'Which location would you like to visit?\n\n'+'\n'.join(f"{i}. {r['label']}: {r['address']}" for i,r in enumerate(locations,1)),{'location_offer':{'option_ids':[r['address'] for r in locations],'pending':True}},[]
    try:options=search_slots(db,scope,prefs,now)
    except ValueError as exc:return str(exc),{},[]
    try:context=context_snapshot(db,scope,project,state,location)
    except (PermissionError,ValueError):
        state.booking_search={**prefs,'property_type_id':None,'unit_id':None,'location':location}
        return 'The property details need to be verified before I can offer that visit. Which property would you like to review?',{},[]
    if not options:
        from .wait_service import wait_offer
        try:return wait_offer(db,scope,outcome,context,prefs)
        except ValueError:return 'Please specify a future date range and timezone for the visit.',{},[]
    offer={'version':VERSION,'slots':[o['starts_at'] for o in options],'options':options,'preferences':prefs,'context':context,
        'property_type_id':property_id,'unit_id':unit_id,'visit_location':location,'duration_minutes':prefs['duration_minutes'],
        'project_timezone':project.timezone or 'UTC','expires_at':(utc(now)+timedelta(minutes=30)).isoformat()}
    return 'Verified visit options:\n\n'+'\n\n'.join(f"{i}. {label(o,prefs)}" for i,o in enumerate(options,1))+'\n\nWhich time would you like me to prepare for confirmation?',{'appointment_offer':offer},[{'type':'request_available_slots'}]


def sync_calendar(db,operation_id):
    """A durable, locked operation with deterministic provider ID; never creates a reservation."""
    op=db.query(SalesBookingOperation).filter_by(id=operation_id).with_for_update(skip_locked=True).first()
    if not op or op.calendar_status in {'synced','simulation','review','cancelled'}:return
    meeting=db.query(Meeting).filter_by(id=op.meeting_id).populate_existing().with_for_update().first();project=db.get(Project,op.project_id)
    if not meeting or not project or project.company_id!=op.company_id or meeting.lead_id!=op.lead_id or meeting.project_id!=op.project_id:raise PermissionError('Calendar operation scope changed.')
    if meeting.status not in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED} or meeting.meeting_time<=workflow_now(datetime):
        op.calendar_status='cancelled';db.commit();return
    if meeting.is_demo:
        op.calendar_status='simulation';db.commit();return
    saved=op.snapshot_json or {}
    if not all(key in saved for key in ('option','context')) or not all(
        key in saved['option'] for key in ('starts_at','sales_user_id')) or not isinstance(saved['context'].get('location'),dict):
        op.calendar_status='review';op.last_error='HistoricalBookingSnapshotIncomplete';db.commit();return
    if (utc(meeting.meeting_time).isoformat()!=saved['option']['starts_at'] or meeting.assigned_sales_user_id!=saved['option']['sales_user_id'] or
        meeting.duration_minutes!=saved['context']['duration_minutes'] or meeting.visit_address!=saved['context']['location']['address']):
        op.calendar_status='review';op.last_error='BookingChanged';db.commit();return
    user=db.query(User).filter_by(id=meeting.assigned_sales_user_id,company_id=op.company_id,deleted_at=None).first()
    connection=db.query(CalendarConnection).filter_by(user_id=meeting.assigned_sales_user_id,provider='google',status='connected').first() if user else None
    if not connection:
        op.calendar_status='waiting_connection';op.next_attempt_at=workflow_now(datetime)+timedelta(minutes=10);meeting.calendar_sync_status='not_connected';db.commit();return
    from app.integrations.gcalendar_client import create_calendar_event_for_connection
    op.calendar_attempts+=1
    try:
        lead=db.get(Lead,op.lead_id)
        event=create_calendar_event_for_connection(db,connection,title=f"{op.snapshot_json['context']['project_name']} visit with {lead.full_name}",
            description='Confirmed property visit.',location=meeting.visit_address or '',start_time=meeting.meeting_time,
            end_time=meeting.meeting_time+timedelta(minutes=meeting.duration_minutes),timezone_name=meeting.visit_context['timezone'],
            attendee_email=lead.email if not lead.is_opt_out else None,event_id='bp'+meeting.id.replace('-',''))
        meeting.gcal_event_id=event['id'];meeting.meeting_url=event.get('htmlLink');meeting.calendar_sync_status='synced';op.calendar_status='synced';op.last_error=None
    except Exception as exc:
        meeting.calendar_sync_status='failed';op.calendar_status='review' if op.calendar_attempts>=5 else 'retry'
        op.last_error=type(exc).__name__;op.next_attempt_at=workflow_now(datetime)+timedelta(minutes=min(60,2**op.calendar_attempts))
    db.commit()


def retry_calendars(db,limit=10):
    from .active_service import selected_policy
    from .next_flow import selected
    from .dialogue_store import Scope
    from .reschedule_models import SalesRescheduleOperation
    replacement=db.query(SalesRescheduleOperation.id).filter(
        SalesRescheduleOperation.replacement_booking_operation_id==SalesBookingOperation.id).exists()
    # G owns both activation scopes and the ordered replacement/cleanup effect.
    query=db.query(SalesBookingOperation).filter(~replacement,SalesBookingOperation.calendar_status.in_(['pending','retry','waiting_connection']),
        SalesBookingOperation.next_attempt_at<=workflow_now(datetime))
    # Filter disabled scopes before the batch limit so they cannot starve live work.
    rows=query.order_by(SalesBookingOperation.next_attempt_at).limit(limit).all()
    for row in rows:
        scope=Scope(row.company_id,row.project_id,row.conversation_id,row.lead_id)
        from .effect_recovery import attempt
        attempt(db,SalesBookingOperation,row.id,lambda: sync_calendar(db,row.id))


def enrich_understanding(u,previous_meta,text):
    """Only the immediately preceding backend question can turn a short answer into continuation."""
    from .service import _affirmative_slot_reply
    normalized=' '.join(re.sub(r"[^a-z ]",' ',text.casefold()).split())
    if normalized in {'no','no thanks','no thank you','not now','no more questions','no no more questions','no that s all'} and (
        previous_meta.get('booking_confirmation') or previous_meta.get('post_booking_question')):
        payload=u.model_dump(mode='json')
        payload.update(requests=[{'id':'backend_contextual_decline','topic':'other','subject':None,'polarity':'request','evidence':text}],
            all_of=['backend_contextual_decline'],alternatives=[],requires_clarification=False,clarification_question=None,
            visit=None,appointment_query=None,courtesy={'kind':'decline' if previous_meta.get('booking_confirmation') else 'farewell','evidence':text})
        from .understanding_contract import Understanding
        return Understanding.model_validate(payload)
    if u.requires_clarification or u.permits('appointment'):return u
    resume=(previous_meta.get('booking_confirmation') and _affirmative_slot_reply(text)) or (
        previous_meta.get('booking_property_question') and any(r.kind in {'property','unit'} for r in u.references) and
        all(r.topic.value in {'other','property_details','catalog'} for r in u.requests if r.polarity=='request'))
    if not resume:return u
    if previous_meta.get('material_offer') or previous_meta.get('release_offer'):return u
    payload=u.model_dump(mode='json')
    payload['requests'].append({'id':'backend_visit_continuation','topic':'appointment','subject':None,'polarity':'request','evidence':text})
    payload['all_of'].append('backend_visit_continuation')
    from .understanding_contract import Understanding
    return Understanding.model_validate(payload)


def apply_courtesy(db,conversation,lead,state):
    u=state.last_understanding
    if not u.courtesy:return
    from app.modules.governance.services import request_attribution
    if u.courtesy.evidence not in request_attribution(u.courtesy.evidence)['current_text']:return
    substantive=any(r.polarity=='request' and r.topic.value!='other' for r in u.requests)
    if u.courtesy.kind=='farewell':stop_cadence(db,conversation,lead,state,'cancelled' if state.cadence_stop_reason=='cancelled' else 'farewell')
    elif u.courtesy.kind=='decline' and not substantive:
        state.booking_proposal=None
        stop_cadence(db,conversation,lead,state,'cancelled' if state.cadence_stop_reason=='cancelled' else 'declined')
