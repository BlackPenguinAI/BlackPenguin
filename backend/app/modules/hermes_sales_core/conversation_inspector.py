"""HEI-04: bounded, read-only, evidence-based projection for the existing Agent view.

No runtime, prompt, tool arguments, raw state, message body, token or external
URL crosses this boundary. The tenant route authorizes the user first. Scope is
revalidated here so a reused provider thread cannot leak a previous opportunity.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from math import isfinite
import re
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_

from .bp_models import HermesSalesState, HermesSalesStateEvent
from .bp_operation_models import HermesSalesOperation
from .contracts import TurnScope
from .bp_context import require_scoped_entities
from .engine_selection import routing_status
from .staff_models import HermesGlobalSettings
from .tool_schemas import SCHEMAS
from app.modules.sales_agent.models import (
    AgentRun, SalesMessage, SalesConversationLeadContext, SalesInboundJob,
    SalesFollowUpJob, OutboundMessage,
)
from app.modules.sales_agent.conversation_scope import scoped_messages_query
from app.modules.projects.models import ProjectSalesAsset, SalesAssetShare
from app.modules.sales_crm.models import Meeting, MeetingStatus
from app.modules.users.models import User

VERSION = 'hermes-conversation-inspector/1.0'
LIMITS = {'messages': 60, 'runs': 20, 'events': 20, 'operations': 20,
          'materials': 30, 'visits': 20, 'jobs': 20, 'tools_per_run': 15}
ACCEPTED = {'sent', 'accepted', 'delivered', 'read'}
DELIVERED = {'delivered', 'read'}
STATUS = {'received','processed','sent','accepted','delivered','read','queued','sending',
          'scheduled','pending','running','completed','confirmed','cancelled','rescheduled',
          'failed','review','retry','awaiting_resume','superseded','delivery_unknown',
          'delivery_failed','undelivered','blocked','processing','pending_delivery',
          'issued_not_sent','link_issued_for_simulation','provider_accepted','draft','idle',
          'selected','recap_required','awaiting_confirmation','execution_requested','committed',
          'expired','unavailable','not_connected','synced','simulation','simulation_ready',
          'waiting_connection','waiting_old_connection','waiting_new_calendar','pending_backend_share',
          'ready','unknown','paused','not_sent','in_app_only','declared','withdrawn','declined',
          'active','past','approved','rejected','executed','requested','stale','invalidated'}
PHASES = {'discovery','exploration','qualification','property_exploration','property_details',
          'visit_planning','visit_confirmation','appointment_confirmed','handoff','closing',
          'comparison','booking','details','search','material_sharing','follow_up','paused','human_review'}
BUDGET_MODES = {'unknown','cap','floor','range','target','fixed_funds','exact_price','exact'}
BED_MODES = {'unknown','minimum','maximum','range','preferred','exact','any'}
TAGS = {'brochure','floor_plan','gallery_image','unit_sheet','price_list','amenities',
        'location_map','virtual_tour','legal_disclaimer','other'}


def obj(value):
    return value if isinstance(value, dict) else {}


def seq(value, n=60):
    return value[:n] if isinstance(value, list) else []


def utc(value):
    if isinstance(value, str):
        try: value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError): return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc) if isinstance(value, datetime) else None


def stamp(value):
    parsed = utc(value)
    return parsed.isoformat() if parsed else None


def number(value):
    return value if type(value) in (int, float) and isfinite(value) and 0 <= value <= 1e12 else None


def enum(value, allowed, default='unknown'):
    return value if isinstance(value, str) and value in allowed else default


def label(value, limit=180):
    # No URLs (including unprefixed capability paths), control characters or
    # credential-shaped strings in display labels/free-text commercial facts.
    if not isinstance(value, str): return None
    from app.modules.sales_agent.monitor import redact
    value = redact(value)
    value = re.sub(r'(?i)https?://\S+|/(?:api/v1/)?projects/(?:a|shared-assets)/\S+', '[link omitted]', value)
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', value).strip()
    return value[:limit] or None


def code(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', value) else None


def scoped_query(db, conversation):
    q = scoped_messages_query(db, conversation).filter(SalesMessage.channel == conversation.channel)
    meta = SalesMessage.metadata_json
    # Explicit conflicting attribution is never admitted, even when the
    # activation timestamp matches. Legacy un-attributed rows are allowed
    # only when the physical thread has never been reused.
    contexts = db.query(SalesConversationLeadContext).filter_by(conversation_id=conversation.id).all()
    if contexts and (sum(bool(c.is_active) for c in contexts)!=1 or not any(c.is_active and c.lead_id==conversation.lead_id for c in contexts)):
        raise HTTPException(404,'Conversation not found.')
    if len(contexts) > 1:
        return q.filter(meta['lead_id'].as_string() == conversation.lead_id,
                        meta['project_id'].as_string() == conversation.project_id)
    return q.filter(or_(meta['lead_id'].as_string() == conversation.lead_id, meta['lead_id'].as_string().is_(None)),
                    or_(meta['project_id'].as_string() == conversation.project_id, meta['project_id'].as_string().is_(None)))


def run_engine(run):
    if not run or not isinstance(run.graph_version, str) or not run.graph_version:
        return 'unknown'
    return 'hermes' if run.graph_version.startswith('hermes/') else 'langgraph' if run.graph_version.startswith(('sales-', 'langgraph')) else 'unknown'


def verified_run_labels(db, conversation, messages):
    """Chat attribution from stored AgentRun/inbound bindings, not selected engine.

    Bounded batches avoid per-message query growth; an unbound historical AI
    response is deliberately unattributed. Caller provides scoped messages.
    """
    ids={m.id for m in messages if m.direction=='inbound' and m.role=='user'}
    run_ids={r for m in messages if isinstance((r:=obj(m.metadata_json).get('agent_run_id')),str) and len(r)<=36}
    owned={}
    ordered=sorted(run_ids)
    for start in range(0,len(ordered),100):
        for r in db.query(AgentRun).filter(AgentRun.conversation_id==conversation.id,AgentRun.id.in_(ordered[start:start+100])).all():
            data=obj(r.input_snapshot);pin=obj(data.get('sales_engine_pin'))
            if not isinstance(data.get('message_id'),str) or data['message_id'] not in ids:continue
            if pin and any(pin.get(k)!=getattr(conversation,k if k!='conversation_id' else 'id') for k in ('company_id','project_id','lead_id','conversation_id')):continue
            owned[r.id]=r
    labels={}
    for m in messages:
        meta=obj(m.metadata_json);rid=meta.get('agent_run_id')
        if m.role=='user':labels[m.id]='lead';continue
        if m.role=='human':labels[m.id]='human';continue
        if m.role!='assistant':labels[m.id]='unknown';continue
        r=owned.get(rid) if isinstance(rid,str) else None
        # Deterministic Hermes messages intentionally do not own an AgentRun.
        if r:
            out_id=meta.get('outbound_message_id')
            out=db.get(OutboundMessage,out_id) if isinstance(out_id,str) else None
            persisted_output=obj(obj(r.output_snapshot).get('metadata'))
            output_ids=[persisted_output.get('message_id'),*seq(persisted_output.get('message_ids'),40)]
            exact_out=bool(out and out.conversation_id==conversation.id and out.agent_run_id==r.id
                and out.channel==conversation.channel and out.content==m.content
                and out.provider_message_id==m.provider_message_id)
            exact_sim=conversation.channel=='simulation' and r.mode=='simulation' and m.id in output_ids
            if exact_out or exact_sim:
                labels[m.id]=run_engine(r);continue
        out_id=meta.get('outbound_message_id')
        control_out=db.get(OutboundMessage,out_id) if isinstance(out_id,str) else None
        exact_control=bool(control_out and control_out.conversation_id==conversation.id and control_out.channel==conversation.channel
            and control_out.content==m.content and control_out.provider_message_id==m.provider_message_id and not control_out.agent_run_id)
        if exact_control and meta.get('lead_id')==conversation.lead_id and meta.get('project_id')==conversation.project_id:
            if meta.get('engine')=='hermes-control/1' and isinstance(meta.get('hermes_inbound_message_id'),str) and meta['hermes_inbound_message_id'] in ids:
                labels[m.id]='hermes_control';continue
            job_id=meta.get('hermes_scheduled_job_id')
            if meta.get('engine')=='hermes-scheduled/1' and isinstance(job_id,str):
                job=db.query(SalesFollowUpJob).filter_by(id=job_id,conversation_id=conversation.id).first()
                payload=obj(job.payload_json) if job else {}
                if payload.get('lead_id')==conversation.lead_id and payload.get('project_id')==conversation.project_id:
                    labels[m.id]='hermes_scheduled';continue
        labels[m.id]='unknown'
    return labels


def inspect_conversation(db, conversation):
    scope = TurnScope(conversation.company_id, conversation.project_id, conversation.id, conversation.lead_id)
    try:
        _, project, lead, current = require_scoped_entities(db, scope)
    except PermissionError as exc:
        raise HTTPException(404, 'Conversation not found.') from exc
    contexts = db.query(SalesConversationLeadContext).filter_by(conversation_id=current.id).all()
    active = [c for c in contexts if c.is_active]
    if contexts and (len(active) != 1 or active[0].lead_id != lead.id):
        raise HTTPException(404, 'Conversation not found.')
    activation = utc(active[0].activated_at) if active else None
    now = datetime.now(timezone.utc)
    q = scoped_query(db, current)
    message_cache = {}
    def message(mid):
        if not isinstance(mid, str) or not 1 <= len(mid) <= 36: return None
        if mid not in message_cache: message_cache[mid] = q.filter(SalesMessage.id == mid).one_or_none()
        return message_cache[mid]
    def source(mid):
        row = message(mid)
        return {'message_id':row.id, 'at':stamp(row.created_at)} if row and row.direction == 'inbound' and row.role == 'user' else None
    def accepted_out(mid):
        row = message(mid)
        if not row or row.direction != 'outbound' or row.role != 'assistant' or row.status not in ACCEPTED: return None
        if current.channel == 'simulation': return row
        out = db.get(OutboundMessage, obj(row.metadata_json).get('outbound_message_id')) if obj(row.metadata_json).get('outbound_message_id') else None
        if (out and out.conversation_id == current.id and out.channel == current.channel and row.provider_message_id
                and out.provider_message_id == row.provider_message_id and out.content == row.content and out.status in ACCEPTED):
            return row
        return None

    row = db.query(HermesSalesState).filter_by(**scope.__dict__).one_or_none()
    # State from a prior activation is historical, not the new enquiry.
    stale_activation = bool(row and activation and (not utc(row.updated_at) or utc(row.updated_at) < activation))
    state = obj(row.state_json) if row and not stale_activation else {}
    settings = db.get(HermesGlobalSettings, 'global')
    routing = routing_status(settings.configuration if settings else None)
    routing = {k:routing[k] for k in ('active_sales_engine','effective_sales_engine','target_default_engine','hermes_live_ready','error_code')}
    runs = db.query(AgentRun).filter(AgentRun.conversation_id == current.id,
        AgentRun.input_snapshot['message_id'].as_string().in_(q.with_entities(SalesMessage.id).filter_by(direction='inbound',role='user').statement)
    ).order_by(AgentRun.started_at.desc(), AgentRun.id.desc()).limit(LIMITS['runs']).all()
    run_by_id = {}
    for run in runs:
        pin = obj(obj(run.input_snapshot).get('sales_engine_pin'))
        if pin and any(pin.get(k) != v for k,v in scope.__dict__.items()): continue
        if activation and utc(run.started_at) < activation: continue
        run_by_id[run.id] = run
    engine=run_engine
    def message_engine(m):
        return message_labels.get(m.id,'unknown')

    messages = q.order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).limit(LIMITS['messages']).all()
    # Include original inbounds referenced by bounded recent runs, even if
    # they fell just outside the message display window.
    label_rows={m.id:m for m in messages}
    for r in run_by_id.values():
        m=message(obj(r.input_snapshot).get('message_id'))
        if m:label_rows[m.id]=m
    message_labels=verified_run_labels(db,current,list(label_rows.values()))
    latest = next((m for m in messages if m.direction=='outbound' and m.role in {'assistant','human'} and m.status in ACCEPTED),None)
    last_engine = message_engine(latest) if latest else 'unknown'
    last_run_engine = engine(next(iter(run_by_id.values()), None))
    boundary = obj(current.continuity_json)
    valid_boundary = boundary.get('lead_id') == lead.id and boundary.get('project_id') == project.id
    # A pending visit or numbered offer is valid only within the current
    # control episode and actual accepted Hermes response. Historical focus
    # can be displayed, but never described as the active engine's current fact.
    latest_meta = obj(latest.metadata_json) if latest else {}
    current_lane = ('hermes' if last_run_engine=='hermes' or last_engine.startswith('hermes') else last_run_engine)
    if valid_boundary and boundary.get('sales_engine_boundary') in {'hermes','langgraph'}:
        current_lane = boundary['sales_engine_boundary']
    historical = bool(row and (stale_activation or current_lane=='langgraph'))
    offer_valid = bool(state and not historical and not current.is_paused and latest and last_engine=='hermes'
        and (current.channel=='simulation' or valid_boundary and latest_meta.get('continuity_epoch')==boundary.get('epoch')))

    # Approved commercial catalog only. No exposure of links, descriptions,
    # unreviewed source rows or price inference from a UUID.
    from app.modules.onboarding_versions import active_approved
    from app.modules.sales_agent.commercial_context import build_commercial_context
    commercial = build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,
        channel='sms' if current.channel=='simulation' else current.channel) if state and active_approved(project.profile) else {}
    catalog = []
    for p in seq(commercial.get('property_types'), 500):
        p=obj(p); ref=p.get('id'); name=label(p.get('property_type'))
        if isinstance(ref,str) and name:
            catalog.append({'id':ref,'reference':ref,'name':name,'kind':'property_type','bedrooms':number(p.get('bedrooms')),
                            'price':number(p.get('starting_price')),'price_kind':'starting','currency':currency(p.get('currency'))})
    if commercial.get('inventory_source')=='individual_units':
        for p in seq(commercial.get('inventory'),500):
            p=obj(p); ref=p.get('unit_code'); name=label(p.get('property_type')); unit=label(ref)
            if isinstance(p.get('id'),str) and unit:
                catalog.append({'id':p['id'],'reference':ref,'name':f'{name} ({unit})' if name and name!=unit else unit,
                    'kind':'unit','bedrooms':number(p.get('bedrooms')),'price':number(p.get('price')),'price_kind':'listing','currency':currency(p.get('currency'))})
    def prop(ref):
        if not isinstance(ref,str):return None
        found=[p for p in catalog if ref in (p['id'],p['reference'])]
        return found[0] if len(found)==1 else None
    focus_raw=obj(state.get('conversation_focus'))
    focus=prop(focus_raw.get('unit_id') or focus_raw.get('property_type_id')) if focus_raw.get('project_id')==project.id and not focus_raw.get('ambiguous') else None
    focus_status='ambiguous' if focus_raw.get('ambiguous') else 'resolved' if focus else 'not_captured'
    if not focus and (focus_raw.get('unit_id') or focus_raw.get('property_type_id')) and focus_status!='ambiguous':focus_status='not_in_approved_catalog'
    preferences=obj(state.get('search_preferences')); b=obj(preferences.get('budget')); beds=obj(preferences.get('bedrooms'))
    saved={'revision':number(preferences.get('revision')),'source':source(preferences.get('last_source_message_id')),
           'budget':{'mode':enum(b.get('mode'),BUDGET_MODES),'currency':currency(b.get('currency')),**{k:number(b.get(k)) for k in ('minimum_usd','maximum_usd','target_usd','exact_price_usd')}},
           'bedrooms':{'mode':enum(beds.get('mode'),BED_MODES),**{k:number(beds.get(k)) for k in ('minimum','maximum','preferred')}}}
    from app.modules.sales_agent.lead_profile import resolve
    crm = obj(resolve(lead).get('current'))
    facts = {}
    for key in ('purchase_timeline','budget','budget_minimum','budget_maximum','budget_currency','bedrooms'):
        record=obj(crm.get(key)); value=record.get('value'); status=enum(record.get('status'),{'declared','confirmed','declined','withdrawn'})
        if isinstance(value,dict):value={k:number(v) if k!='currency' else currency(v) for k,v in value.items() if k in {'minimum','maximum','amount','currency'}}
        else:value=label(value) if isinstance(value,str) else number(value)
        facts[key]={'value':value if status in {'declared','confirmed'} else None,'status':status,
                    'source':enum(record.get('source'),{'active_conversation','agent_conversation','meta_form','manual_registration','staff_verified','approved_catalog_selection','source_answer','legacy_profile','conflicting_sources'}),
                    'evidence':source(obj(record.get('source_ref')).get('message_id')),'at':stamp(record.get('captured_at'))}
    search=obj(state.get('active_search')); criteria=obj(search.get('criteria'))
    search_info = None
    if search:
        search_info={'scope':enum(search.get('scope'),{'temporary','permanent'}),'criteria':filter_values(criteria),
                     'matches':[p for x in seq(search.get('matching_unit_ids'),20) if (p:=prop(x))],
                     'source':source(search.get('source_inbound_message_id') or search.get('source_message_id')),'at':stamp(search.get('created_at')),
                     'match_count':number(search.get('match_count'))}
    draft=obj(state.get('visit_draft')); req=obj(state.get('confirmation_request')); offer=obj(state.get('last_slot_search'))
    def date_text(value):
        return value if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value) else None
    def clock_text(value):
        return value if isinstance(value,str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value) else None
    def proposal_info(value):
        return {'property':prop(value.get('unit_id') or value.get('property_type_id')),
                'date':date_text(value.get('date')),'time':clock_text(value.get('start_time')),
                'timezone':zone(value.get('timezone')),'status':enum(value.get('status'),STATUS),
                'expires_at':stamp(value.get('expires_at'))}
    visit_draft=proposal_info(draft) if draft else None
    if visit_draft and visit_draft['status'] not in {'confirmed','cancelled','rescheduled','committed','idle'} and not offer_valid:
        visit_draft['status']='stale'
    proposal=proposal_info(req) if req else None
    if proposal:
        proposal['kind']=enum(req.get('kind'),{'book','cancel','reschedule','handoff'})
        expiry=utc(req.get('expires_at'))
        if proposal['status'] not in {'committed','confirmed','cancelled','rescheduled'}:
            if not expiry or expiry<=now:proposal['status']='expired'
            elif not offer_valid or (proposal['status']=='awaiting_confirmation' and (not accepted_out(req.get('recap_message_id')) or not latest or latest.id!=req.get('recap_message_id'))):proposal['status']='stale'
        recap=accepted_out(req.get('recap_message_id'))
        from .bp_operation_receipts import recap_visible
        from .live_changes import recap_matches
        valid_recap=bool(recap and (recap_matches(recap.content,req) or (req.get('kind')=='book' and recap_visible(recap.content,req) and (current.channel=='simulation' or all(isinstance(req.get(k),str) and req[k].strip() and req[k].casefold() in recap.content.casefold() for k in ('visit_address','timezone'))))))
        if proposal['status']=='awaiting_confirmation' and not valid_recap:proposal['status']='stale'
        proposal['recap_message_id']=recap.id if valid_recap else None
    slots=[]; expiry=utc(offer.get('expires_at')); offered=accepted_out(offer.get('source_reply_message_id'))
    if offer and offered and offer_valid and expiry and expiry>now:
        slots=[{'date':date_text(obj(x).get('date')),'time':clock_text(obj(x).get('start_time'))} for x in seq(offer.get('options'),12)]
        slots=[x for x in slots if x['date'] and x['time']]
    visits=[]
    for m in db.query(Meeting).filter_by(project_id=project.id,lead_id=lead.id,is_demo=current.channel=='simulation').order_by(Meeting.meeting_time.desc(),Meeting.id).limit(LIMITS['visits']).all():
        ctx=obj(m.visit_context); starts=utc(m.meeting_time); duration=number(m.duration_minutes)
        status=enum(getattr(m.status,'value',m.status),STATUS)
        booked_prop=prop(m.visit_unit_id or m.visit_property_type_id)
        # Historical booking snapshot is authoritative for names/location;
        # never substitute the current enquiry for an old reservation.
        booked_name=label(ctx.get('property_type_name')) or label(ctx.get('unit_code')) or (booked_prop or {}).get('name')
        advisor=db.query(User).filter_by(id=m.assigned_sales_user_id,company_id=scope.company_id,deleted_at=None).first() if m.assigned_sales_user_id else None
        timezone_name=zone(ctx.get('timezone')) or zone(project.timezone)
        visits.append({'id':m.id,'property_name':booked_name,'status':status,'confirmation_status':enum(m.confirmation_status,STATUS),
            'calendar_status':enum(m.calendar_sync_status,STATUS),'starts_at':stamp(starts),'timezone':timezone_name,
            'duration_minutes':duration,'address':label(m.visit_address,255),'specialist':label(' '.join(x for x in (advisor.first_name,advisor.last_name) if x)) if advisor else None,
            'active':bool(starts and duration is not None and starts+timedelta(minutes=duration)>now and m.status in {MeetingStatus.CONFIRMED,MeetingStatus.SCHEDULED})})
    timeline=[]
    for m in messages:
        timeline.append({'kind':'message','at':stamp(m.created_at),'message_id':m.id,'engine':message_engine(m),
                         'direction':enum(m.direction,{'inbound','outbound'}),'status':enum(m.status,STATUS)})
    for run in run_by_id.values():
        output=obj(run.output_snapshot); observations=[]
        if engine(run)=='hermes':
            for i,item in enumerate(seq(output.get('tool_observations'),LIMITS['tools_per_run']),1):
                item=obj(item); tool=item.get('tool')
                if isinstance(tool,str) and tool in SCHEMAS:
                    observations.append({'order':i,'tool':tool,'status':enum(item.get('status'),{'executed','rejected'}),'error_code':code(item.get('error_code'))})
        timeline.append({'kind':'run','at':stamp(run.started_at),'ended_at':stamp(run.completed_at),'engine':engine(run),'run_id':run.id,
            'message_id':obj(run.input_snapshot).get('message_id'),'status':enum(run.status,STATUS),'mode':enum(run.mode,{'simulation','live'}),
            'error_code':code(run.error_code),'tools':observations})
    events_q=db.query(HermesSalesStateEvent).filter_by(**scope.__dict__)
    ops_q=db.query(HermesSalesOperation).filter_by(**scope.__dict__).filter(HermesSalesOperation.inbound_message_id.in_(q.with_entities(SalesMessage.id).statement))
    if activation:
        events_q=events_q.filter(HermesSalesStateEvent.recorded_at>=activation)
        ops_q=ops_q.filter(HermesSalesOperation.created_at>=activation)
    for e in events_q.order_by(HermesSalesStateEvent.revision.desc()).limit(LIMITS['events']).all():
        timeline.append({'kind':'state','at':stamp(e.recorded_at),'revision':e.revision,'status':enum(e.event_type,{'state_update','outbound_choice_receipt','simulation_receipt','simulation_operation'}),'engine':'hermes'})
    operations=[]
    for op in ops_q.order_by(HermesSalesOperation.created_at.desc(),HermesSalesOperation.id).limit(LIMITS['operations']).all():
        r=obj(op.result_json)
        record={'kind':'operation','at':stamp(op.created_at),'operation_id':op.id,'message_id':op.inbound_message_id,'engine':'hermes',
                'operation':enum(op.operation_type,{'book','cancel','reschedule','material','handoff'}),'status':enum(op.status,STATUS),
                'result':enum(r.get('status'),STATUS)}
        operations.append(record);timeline.append(record)
    # Job status can be more informative than a completed LLM run. Scope by
    # the actual inbound and never expose raw error_message or job payload.
    jobs=db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==current.id,
        SalesInboundJob.message_id.in_(q.with_entities(SalesMessage.id).statement)).order_by(SalesInboundJob.created_at.desc()).limit(LIMITS['jobs']).all()
    for job in jobs:
        if job.status in {'review','retry','failed','awaiting_resume','processing','pending'}:
            timeline.append({'kind':'job','at':stamp(job.processed_at or job.claimed_at or job.created_at),'message_id':job.message_id,
                             'status':enum(job.status,STATUS),'error_code':code(job.error_code)})
    # Material receipts are independent of model text and of state.shared_media.
    # Issued access is not a sent message; queued is not delivery. Never return
    # a token hash, URL, provider ID or the underlying outbox body.
    materials=[]
    from hashlib import sha256
    from app.modules.projects.asset_coverage import matches
    approved_ids={x.get('asset_id') for x in seq(commercial.get('available_assets'),500) if isinstance(x,dict) and isinstance(x.get('asset_id'),str)}
    shares=db.query(SalesAssetShare).filter_by(company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id,
        channel='sms' if current.channel=='simulation' else current.channel).filter(SalesAssetShare.agent_run_id.in_(list(run_by_id))).order_by(SalesAssetShare.created_at.desc()).limit(LIMITS['materials']).all()
    seen=set()
    for s in shares:
        asset=db.query(ProjectSalesAsset).filter_by(id=s.sales_asset_id,company_id=scope.company_id,project_id=scope.project_id).first() if s.sales_asset_id else None
        if not asset:continue
        seen.add(asset.id)
        out=db.get(OutboundMessage,s.outbound_message_id) if s.outbound_message_id else None
        status='issued_not_sent';mid=None
        if out:
            status='unknown'
            if out.conversation_id==current.id and out.agent_run_id==s.agent_run_id and out.channel==current.channel and out.provider_message_id:
                msg=q.filter_by(provider_message_id=out.provider_message_id,direction='outbound',role='assistant').first()
                meta=obj(msg.metadata_json) if msg else {}
                if msg and meta.get('outbound_message_id')==out.id and meta.get('agent_run_id')==s.agent_run_id and s.id in seq(meta.get('sales_asset_share_ids'),40) and msg.content==out.content and s.token_hash in {sha256(t.rstrip('.,;)').encode()).hexdigest() for t in re.findall(r'/projects/a/([^\s]+)',msg.content)}:
                    mid=msg.id
                    status='delivered' if msg.status in DELIVERED and out.status in DELIVERED else 'provider_accepted' if msg.status in ACCEPTED and out.status in ACCEPTED else 'unknown' if out.status in ACCEPTED else enum(out.status,STATUS)
        materials.append({'name':label(asset.display_name),'tags':tags(asset),'asset_id':asset.id,'status':status,
            'message_id':mid,'engine':engine(run_by_id.get(s.agent_run_id)),'at':stamp(s.created_at),'access_status':'revoked' if s.revoked else 'expired' if utc(s.expires_at) and utc(s.expires_at)<=now else 'not_currently_approved' if asset.id not in approved_ids else 'not_revalidated'})
    if focus and len(materials)<LIMITS['materials']:
        for asset in db.query(ProjectSalesAsset).filter(ProjectSalesAsset.id.in_(approved_ids-seen),ProjectSalesAsset.project_id==project.id,ProjectSalesAsset.company_id==scope.company_id).limit(100).all():
            if not matches(asset,property_id=focus['id'] if focus['kind']=='property_type' else None,unit_id=focus['id'] if focus['kind']=='unit' else None):continue
            materials.append({'name':label(asset.display_name),'tags':tags(asset),'asset_id':asset.id,'status':'approved_catalog','access_status':'not_issued'})
            if len(materials)>=LIMITS['materials']:break
    menu=obj(state.get('last_presented_choice_set'))
    presented=[]
    delivered_menu=accepted_out(menu.get('source_reply_message_id'))
    from .bp_operation_receipts import visible_menu
    options=menu.get('options')
    valid_options=isinstance(options,list) and 2<=len(options)<=9 and all(isinstance(x,dict) and type(x.get('index')) is int and x['index']==i and isinstance(x.get('label'),str) and x['label'].strip() for i,x in enumerate(options,1))
    if offer_valid and delivered_menu and latest and latest.id==delivered_menu.id and menu.get('type')=='property' and valid_options and visible_menu(delivered_menu.content,menu):
        # Only expose catalog-resolved, actually presented options, not raw
        # model labels or hidden tool arguments.
        if menu.get('type')=='property':
            presented=[p for x in seq(menu.get('options'),10) if (p:=prop(obj(x).get('unit_id')))]
    phase=enum(state.get('conversation_phase'),PHASES) if state else None
    phase_source='persisted' if phase else None
    # Some older runtime states only persist the discovery phase. Describe
    # observable activity instead of manufacturing a persisted phase.
    if state and not historical and phase in {'discovery','unknown'}:
        if current.is_paused:phase='paused';phase_source='observed'
        elif proposal and proposal['status']=='awaiting_confirmation':phase='visit_confirmation';phase_source='observed'
        elif visit_draft and visit_draft['status']=='selected':phase='visit_planning';phase_source='observed'
        elif any(v['active'] for v in visits):phase='appointment_confirmed';phase_source='observed'
        elif focus:phase='property_exploration';phase_source='observed'
    timeline.sort(key=lambda x:x.get('at') or '',reverse=True)
    return {'version':VERSION,'scope':scope.__dict__,'read_only':True,'routing':routing,'live_routing_enabled':routing['hermes_live_ready'],
            'has_state':bool(state),'historical_state':historical,'revision':row.revision if state else None,
            'engine_version':row.engine_version if state and re.fullmatch(r'[a-zA-Z0-9/._-]{1,64}',row.engine_version or '') else None,'updated_at':stamp(row.updated_at) if state else None,
            'last_engine':last_engine,'last_run_engine':last_run_engine,'conversation_engine':current_lane,'channel':current.channel,
            'project_name':label(project.name),'timezone':zone(project.timezone),
            'phase':phase,'phase_source':phase_source,'focus':focus,'focus_status':focus_status,'presented_properties':presented,
            'primary_preferences':saved,'crm_facts':facts,'active_search':search_info,'property_filters':filter_values(obj(state.get('property_filters'))),
            'visit_draft':visit_draft,'confirmation':proposal,'visit_planning_paused':bool(state.get('visit_planning_paused')),
            'slot_offer':{'slots':slots,'expires_at':stamp(expiry),'timezone':zone(offer.get('timezone')),'property':prop(offer.get('unit_id')),'status':'previously_checked' if slots else 'stale_or_unverified'} if offer else None,
            'visits':visits,'materials':materials,'operations':operations,'timeline':timeline[:120],'limits':LIMITS}


def currency(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Z]{3}',value) else None


def zone(value):
    if not isinstance(value,str) or len(value)>80:return None
    try:return str(ZoneInfo(value))
    except (ValueError,KeyError):return None


def filter_values(value):
    result={}
    for k in ('bedrooms','bedrooms_min','bedrooms_max','min_price_usd','max_price_usd','min_price','max_price',
              'min_area_sqm','max_area_sqm','min_bathrooms','max_bathrooms','min_parking_spaces','relative_price_lt','relative_price_gt'):
        if number(value.get(k)) is not None:result[k]=number(value[k])
    if type(value.get('private_backyard')) is bool:result['private_backyard']=value['private_backyard']
    if isinstance(value.get('kitchen_layout'),str) and value.get('kitchen_layout') in ('open','closed','open_plan','separate'):result['kitchen_layout']=value['kitchen_layout']
    if isinstance(value.get('bedrooms_any'),list):result['bedrooms_any']=[x for x in value['bedrooms_any'][:10] if number(x) is not None]
    return result


def tags(asset):
    return [t for t in seq(asset.content_tags or [asset.asset_type],20) if isinstance(t,str) and t in TAGS]
