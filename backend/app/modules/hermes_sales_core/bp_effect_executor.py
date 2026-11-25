"""Explicit P04 simulation-only, fail-closed business effect executor.

No HTTP route, worker hook or production activation. This deliberately DOES
NOT call the LangGraph planner or its coordinator. It reuses BP scheduling,
asset approval and ORM models inside one caller-owned SQLAlchemy transaction.
Do not dispatch assistant success text until the caller has committed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from hashlib import sha256
import json
import re
from typing import Any

from .bp_context import require_scoped_entities
from .bp_operation_models import HermesSalesOperation
from .bp_operation_receipts import booking_fingerprint, evidence_live_inbound
from .bp_operational_port import AFFIRMATIVE, CANCEL_DIRECT, _fresh, _now, _timestamp
from .bp_state_store import HermesStateConflict, load, save
from .contracts import TurnScope

HUMAN_REQUEST = re.compile(
    r'\b(?:i\s+(?:want|need|would like)\s+to\s+(?:talk|speak)\s+(?:to|with)\s+(?:a\s+)?'
    r'(?:human|person|sales\s+representative|agent)|'
    r'please\s+(?:connect|transfer)\s+me\s+(?:to|with)\s+(?:a\s+)?(?:human|person|sales\s+representative)|'
    r'i\s+want\s+a\s+human)\b', re.I)


def _no_live(db, scope: TurnScope, *, allow_review_replay: bool = False):
    _, project, lead, conversation = require_scoped_entities(db, scope)
    if conversation.channel != 'simulation' or not bool(lead.is_demo):
        raise PermissionError('P04 actions require both a simulation conversation and a demo lead')
    if lead.deleted_at or lead.is_opt_out or (
            lead.agent_status == 'human_control' and not allow_review_replay):
        raise PermissionError('The lead is opted out, deleted or under human control')
    if lead.consent_status not in ('granted','granted_simulation'):
        raise PermissionError('Sales consent is required before any simulation effect')
    return project, lead, conversation


def _meeting(db, scope, meeting_id, *, lock=True):
    from app.modules.sales_crm.models import Meeting, MeetingStatus
    query = db.query(Meeting).filter_by(
        id=meeting_id,lead_id=scope.lead_id,project_id=scope.project_id,is_demo=True)
    if lock:query=query.with_for_update()
    meeting=query.one_or_none()
    if not meeting or meeting.status not in (MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED):
        raise PermissionError('The simulation reservation is not active or is out of scope')
    if meeting.meeting_time <= datetime.utcnow():
        raise ValueError('The reservation has already started or passed')
    return meeting


def _accepted_request(db, scope, request, inbound_id, *, now):
    if not _fresh(request,now) or request.get('status')!='execution_requested':
        raise PermissionError('There is no fresh explicit, persisted action authorization')
    if request.get('confirmed_inbound_message_id') != inbound_id:
        raise PermissionError('The confirmed action does not belong to this inbound turn')
    inbound = evidence_live_inbound(
        db, scope, inbound_id,
        after_reply_message_id=request.get('recap_message_id') if request['kind'] in ('book','reschedule') else None)
    if request['kind'] in ('book','reschedule'):
        if not request.get('recap_message_id') or not AFFIRMATIVE.fullmatch(inbound.content):
            raise PermissionError('An exact delivered recap and later affirmative buyer message are required')
    elif request['kind']=='cancel' and not CANCEL_DIRECT.search(inbound.content):
        raise PermissionError('Direct buyer cancellation evidence is required')
    return inbound


def _visit_starts(request, now):
    value = _timestamp(request['starts_at_utc'])
    if value <= now or value > now+timedelta(days=14):
        raise ValueError('Selected time is not a future, eligible appointment')
    if value.minute != 0 or value.second != 0:
        raise ValueError('Visits must start on an hourly block')
    try:
        local = value.astimezone(ZoneInfo(request['timezone']))
    except (KeyError,ZoneInfoNotFoundError,ValueError) as exc:
        raise ValueError('Invalid confirmed appointment timezone') from exc
    if local.date().isoformat()!=request.get('date') or local.strftime('%H:%M')!=request.get('start_time'):
        raise PermissionError('Appointment UTC time differs from the confirmed local date/time')
    return value.replace(tzinfo=None)


def _booking(db, scope, lead, project, request, now, *, excluded=None):
    from app.modules.projects.locations import resolve_visit_location
    from app.modules.sales_crm.scheduling import create_agent_appointment
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.sales_agent.execution import sandbox
    from .bp_operational_port import SLOT_DURATION_MINUTES

    from app.modules.onboarding_versions import require_capability
    require_capability(project.profile, 'appointments')
    if request.get('timezone') != project.timezone:
        raise PermissionError('The published project timezone changed after the recap')
    starts = _visit_starts(request,now)
    unit_ref = str(request['unit_id'])
    from app.modules.projects.models import ProjectUnit, ProjectPropertyType
    unit = db.query(ProjectUnit).filter(
        ProjectUnit.project_id==scope.project_id,
        (ProjectUnit.id==unit_ref) | (ProjectUnit.unit_code==unit_ref),
    ).one_or_none()
    prop = None if unit else db.query(ProjectPropertyType).filter_by(
        id=unit_ref,project_id=scope.project_id,review_status='confirmed').one_or_none()
    if not (unit or prop):
        raise PermissionError('The visit property is no longer in the approved project catalog')
    location=resolve_visit_location(project)
    if location is None:
        raise ValueError('A single approved project visit location must be selected first')
    with sandbox(db, db.get(__import__('app.modules.sales_agent.models',fromlist=['SalesConversation']).SalesConversation,scope.conversation_id), now.replace(tzinfo=None)):
        meeting, advisor = create_agent_appointment(
            db,lead=lead,starts_at=starts,duration_minutes=SLOT_DURATION_MINUTES,
            modality='presential',visit_location=location,
            defer_calendar=True,emit_notification=False,capture_visit_context=True,
            visit_property_type_id=prop.id if prop else None,
            visit_unit_id=unit.id if unit else None,
            excluded_meeting=excluded,booking_project_id=scope.project_id,
        )
    if not meeting.is_demo:
        raise PermissionError('Simulation booking unexpectedly created a non-demo meeting')
    receipt=SalesBookingOperation(
        company_id=scope.company_id,project_id=scope.project_id,
        conversation_id=scope.conversation_id,lead_id=scope.lead_id,
        proposal_id=request['id'], meeting_id=meeting.id,
        snapshot_json={'version':'hermes-sales-p04','unit_id':unit_ref,
                       'starts_at_utc':request['starts_at_utc'],
                       'timezone':request['timezone'], 'duration_minutes':SLOT_DURATION_MINUTES},
        calendar_status='simulation',next_attempt_at=now.replace(tzinfo=None))
    db.add(receipt);db.flush()
    return meeting,receipt


def _perform(db, scope, project, lead, conversation, request, now):
    kind = request['kind']
    from app.modules.sales_crm.models import MeetingStatus
    if kind=='book':
        meeting,receipt=_booking(db,scope,lead,project,request,now)
        conversation.stage='appointment_confirmed'
        lead.agent_status='appointment_confirmed'
        return {'status':'confirmed','meeting_id':meeting.id,'booking_operation_id':receipt.id,
                'calendar_status':'simulation','advisor_assigned':bool(meeting.assigned_sales_user_id)}
    if kind=='cancel':
        from app.modules.sales_agent.cancellation_models import SalesCancellationOperation
        meeting=_meeting(db,scope,request['meeting_id'])
        if booking_fingerprint(meeting)!=request['booking_sha256']:
            raise ValueError('The original appointment changed since consent')
        op=SalesCancellationOperation(
            company_id=scope.company_id,project_id=scope.project_id,
            booking_project_id=meeting.project_id,conversation_id=scope.conversation_id,
            lead_id=scope.lead_id,meeting_id=meeting.id,proposal_id=request['id'],
            snapshot_json={'version':'hermes-sales-p04','booking_sha256':request['booking_sha256'],
                           'meeting_id':meeting.id,'cleanup':[]},
            calendar_status='simulation',notification_status='simulation',
            next_attempt_at=now.replace(tzinfo=None),
            notification_next_attempt_at=now.replace(tzinfo=None),
            reason=request.get('reason'),reason_message_id=request.get('confirmed_inbound_message_id'))
        meeting.status=MeetingStatus.CANCELLED
        meeting.confirmation_status='cancelled_by_lead'
        lead.agent_status='active'
        db.add(op);db.flush()
        return {'status':'cancelled','meeting_id':meeting.id,'cancellation_operation_id':op.id,
                'calendar_status':'simulation'}
    if kind=='reschedule':
        from app.modules.sales_agent.booking_models import SalesBookingOperation
        from app.modules.sales_agent.reschedule_models import SalesRescheduleOperation
        db.query(SalesBookingOperation).filter_by(meeting_id=request['meeting_id']).with_for_update().all()
        old=_meeting(db,scope,request['meeting_id'])
        if booking_fingerprint(old)!=request['booking_sha256']:
            raise ValueError('The original visit changed since the approved recap')
        replacement,receipt=_booking(db,scope,lead,project,request,now,excluded=old)
        old.status=MeetingStatus.CANCELLED
        old.confirmation_status='rescheduled'
        op=SalesRescheduleOperation(
            company_id=scope.company_id,project_id=scope.project_id,
            conversation_id=scope.conversation_id,lead_id=scope.lead_id,
            proposal_id=request['id'],original_meeting_id=old.id,
            replacement_meeting_id=replacement.id,
            replacement_booking_operation_id=receipt.id,
            snapshot_json={'version':'hermes-sales-p04','prior_meeting_id':old.id,
                           'new_meeting_id':replacement.id},
            calendar_status='simulation',next_attempt_at=now.replace(tzinfo=None))
        db.add(op);db.flush()
        lead.agent_status='appointment_confirmed'
        return {'status':'rescheduled','original_meeting_id':old.id,
                'meeting_id':replacement.id,'reschedule_operation_id':op.id,
                'calendar_status':'simulation'}
    raise ValueError('Unsupported P04 action kind')


def _material(db, scope, draft, asset_id, lead, conversation, now):
    from app.modules.projects.models import ProjectSalesAsset
    from app.modules.projects.asset_coverage import matches
    from app.modules.sales_agent.material_delivery import snapshot
    from app.modules.projects import asset_share_service, sales_asset_service
    from app.modules.sales_agent.execution import sandbox
    from app.modules.projects.models import ProjectUnit, ProjectPropertyType

    if not _fresh(draft,now) or asset_id not in draft.get('asset_ids',[]):
        raise PermissionError('Asset was not specifically requested within the permitted window')
    if conversation.channel!='simulation':
        raise PermissionError('Only simulated material access can be issued in P04')
    ref=draft['unit_id']
    unit=db.query(ProjectUnit).filter(
        ProjectUnit.project_id==scope.project_id,
        (ProjectUnit.id==ref) | (ProjectUnit.unit_code==ref),
    ).one_or_none()
    prop=None if unit else db.query(ProjectPropertyType).filter_by(id=ref,project_id=scope.project_id,review_status='confirmed').one_or_none()
    if not unit and not prop:
        raise PermissionError('The material target is no longer approved')
    asset=db.query(ProjectSalesAsset).filter_by(
        id=asset_id,company_id=scope.company_id,project_id=scope.project_id).one_or_none()
    if not asset:
        raise PermissionError('Asset is not in this project')
    candidate_ids={x.id for x in sales_asset_service.approved_for_turn(
        db,project_id=scope.project_id,company_id=scope.company_id,channel='sms')}
    if asset.id not in candidate_ids:
        raise PermissionError('Material approval changed')
    subject = 'photos' if draft['subject']=='gallery_image' else draft['subject']
    matched=matches(asset,property_id=prop.id if prop else None,
                    unit_id=unit.id if unit else None,subject=subject)
    if not any(x['coverage']=='requested_tag' for x in matched):
        raise PermissionError('Material coverage for this property is not confirmed')
    snapshot(asset,channel='sms')
    with sandbox(db,conversation,now.replace(tzinfo=None)):
        url,share=asset_share_service.issue(
            db,company_id=scope.company_id,project_id=scope.project_id,
            lead_id=scope.lead_id,source_id=asset.source_id,sales_asset_id=asset.id,
            channel='sms',expires_in_days=1)
    return {'status':'link_issued_for_simulation','asset_id':asset.id,'share_id':share.id,
            'url':url,'delivery':'not_sent'}


def execute_p04_simulation_operation(db, scope: TurnScope, *, expected_revision: int,
                                     inbound_message_id: str, asset_id: str | None = None,
                                     human_request: bool = False, now: datetime | None = None) -> dict[str,Any]:
    """Atomically execute a requested *demo-only* effect; never auto-dispatch.

    Retrying a completed request returns a receipt, never replays the effect.
    Caller MUST commit on success and rollback on exceptions. `result_json`
    does not store share bearer tokens: ephemeral URLs are returned only once.
    """
    now=now or _now()
    if now.tzinfo is None:
        raise ValueError('Clock must be UTC-aware')
    now=now.astimezone(timezone.utc)
    project,lead,conversation=_no_live(db,scope,allow_review_replay=human_request)
    loaded=load(db,scope)
    state=deepcopy(loaded.data)
    if human_request:
        inbound=evidence_live_inbound(db,scope,inbound_message_id)
        if not HUMAN_REQUEST.search(inbound.content):
            raise PermissionError('The lead has not asked for a human')
        request={'id':'human:'+inbound_message_id,'kind':'handoff',
                 'confirmed_inbound_message_id':inbound_message_id}
    elif asset_id is not None:
        request=deepcopy((state.get('offered_assets') or {}).get('pending_request') or {})
        if not request:
            # A completed share request is consumed. Return the durable
            # receipt without ever recreating/revealing its bearer token.
            previous=db.query(HermesSalesOperation).filter_by(
                conversation_id=scope.conversation_id,lead_id=scope.lead_id,
                inbound_message_id=inbound_message_id,operation_type='material').all()
            for op in previous:
                if op.status=='completed' and (op.result_json or {}).get('asset_id')==asset_id:
                    return {**deepcopy(op.result_json),'replayed':True,'delivery':'not_sent'}
        if request.get('source_inbound_message_id') != inbound_message_id:
            raise PermissionError('Material request must be bound to the actual inbound')
        request={**request,'kind':'material'}
        evidence_live_inbound(db,scope,inbound_message_id)
    else:
        request=deepcopy(state.get('confirmation_request') or {})
        if request.get('kind') not in ('book','cancel','reschedule'):
            raise PermissionError('No prepared Hermes operation')
        # Validate consent after looking up an already committed immutable receipt;
        # a harmless retry must not expire simply because the offer TTL passed.
    # After a successful commit the durable state marks the same immutable
    # request 'committed' and appends a result. Reconstruct its original
    # authorization payload for replay checksum, never trust new arguments.
    if request.get('status')=='committed':
        request={k:v for k,v in request.items() if k!='result'}
        request['status']='execution_requested'
    request_id=request.get('id')
    if not isinstance(request_id,str) or not 1 <= len(request_id) <= 64:
        raise ValueError('Invalid P04 operation request ID')
    key=sha256(json.dumps([scope.__dict__,request,asset_id],sort_keys=True,
                          ensure_ascii=False,default=str).encode()).hexdigest()
    prior=db.query(HermesSalesOperation).filter_by(
        conversation_id=scope.conversation_id,lead_id=scope.lead_id,
        request_id=request_id).one_or_none()
    if prior:
        if prior.request_hash!=key:
            raise HermesStateConflict('P04 operation ID was reused for a different request')
        if prior.status!='completed':
            raise HermesStateConflict('P04 operation still needs manual review')
        return {**deepcopy(prior.result_json),'replayed':True}
    if not human_request and asset_id is None:
        _accepted_request(db,scope,request,inbound_message_id,now=now)
        if request['kind'] in ('book','reschedule'):
            offer=state.get('last_slot_search') or {}
            if (not offer.get('source_reply_message_id') or
                    offer.get('proposal_id')!=request.get('proposal_id') or
                    offer.get('unit_id')!=request.get('unit_id') or
                    offer.get('project_id')!=scope.project_id or
                    not any(x.get('starts_at_utc')==request.get('starts_at_utc') and
                                x.get('date')==request.get('date') and
                                x.get('start_time')==request.get('start_time')
                                for x in offer.get('options',[]))):
                raise PermissionError('Confirmed appointment was not in an approved delivered slot offer')
    if human_request and lead.agent_status == 'human_control':
        raise PermissionError('Human review is already active')
    if loaded.revision!=expected_revision:
        raise HermesStateConflict('P04 requested against stale Hermes state')

    from app.modules.sales_crm.models import Lead
    from .bp_models import HermesSalesState
    # SQLite test sessions use nested transactions; PG locks serialize commands
    # by tenant/lead/conversation and CAS safeguards mutable state.
    with db.begin_nested():
        db.query(Lead).filter_by(id=scope.lead_id,company_id=scope.company_id,
                                 project_id=scope.project_id).populate_existing().with_for_update().one()
        db.query(HermesSalesState).filter_by(**scope.__dict__).with_for_update().all()
        # Permissions and lead status can change while awaiting PostgreSQL row
        # locks. Re-read the authoritative rows *after* acquiring the locks.
        project, lead, conversation = _no_live(
            db, scope, allow_review_replay=human_request)
        # Optimistic CAS check after locks; external effects are still blocked.
        if load(db,scope).revision != expected_revision:
            raise HermesStateConflict('Hermes state revision changed while awaiting execution')
        if human_request:
            from app.modules.governance.models import HumanInterventionCase
            case=HumanInterventionCase(
                company_id=scope.company_id,project_id=scope.project_id,
                conversation_id=scope.conversation_id,lead_id=scope.lead_id,
                reason='HUMAN_REQUESTED',evidence=inbound.content[:2000],
                confidence='explicit',status='open',dedupe_key=request_id)
            db.add(case);db.flush()
            conversation.is_paused=True;conversation.pause_reason='Human requested'
            lead.agent_status='human_control'
            state['conversation_phase']='human_review'
            result={'status':'human_review_requested','case_id':case.id,'provider_message_sent':False}
        elif asset_id is not None:
            result=_material(db,scope,request,asset_id,lead,conversation,now)
            state['offered_assets']={}
            saved_media=state.setdefault('shared_media',{})
            saved_media[result['asset_id']]={'share_id':result['share_id'],
                                             'source_message_id':inbound_message_id}
        else:
            result=_perform(db,scope,project,lead,conversation,request,now)
            state['confirmation_request']={**request,'status':'committed',
                                           'result':{k:v for k,v in result.items() if k!='url'}}
            if request['kind'] in ('book','reschedule'):
                state['visit_draft']={**(state.get('visit_draft') or {}),'status':'confirmed'}
            elif request['kind']=='cancel':
                state['visit_draft']={**(state.get('visit_draft') or {}),'status':'idle'}
        clean_result={k:v for k,v in result.items() if k!='url'}
        op=HermesSalesOperation(**scope.__dict__,inbound_message_id=inbound_message_id,
                                request_id=request_id,operation_type=request['kind'],
                                request_hash=key,status='completed',result_json=clean_result)
        db.add(op)
        save(db,scope,expected_revision=expected_revision,
             event_key='p04:'+request_id,state=state,event_type='simulation_operation')
        db.flush()
    return {**result,'replayed':False,'delivery':'not_sent'}
