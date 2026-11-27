"""HEI-03B.3: inbound job handler, shared dispatcher, exact receipts.

The API process never imports or invokes the Nous SDK. A private SDK service
prepares the immutable draft using the pinned AgentRun; provider effects stay
in the existing BlackPenguin worker. The release readiness gate stays closed.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import logging
import os
import traceback
from pathlib import PurePath

from .contracts import TurnScope
from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, LIVE_ENGINE_VERSION
from .provider_delivery import (ENGINE, CONTROL_ENGINE, STOP_REPLY, HANDOFF_REPLY,
                                ReceiptPending, record_plan, receipts, build_plan)

SDK_URL = 'http://bp-hermes:8080/internal/prepare'
MAX_RECEIPT_ATTEMPTS = 10
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def request_sdk_draft(job_id, run_id):
    """Fixed private origin, no redirects or proxy, IDs only, bounded timeout."""
    import httpx
    token=os.environ.get('HERMES_INTERNAL_TOKEN','')
    if len(token)<32:
        raise ProductionToolError('Private Hermes transport is not configured.')
    async with httpx.AsyncClient(timeout=httpx.Timeout(100.0,connect=5.0),follow_redirects=False,trust_env=False) as client:
        response=await client.post(SDK_URL,json={'job_id':job_id,'run_id':run_id},
            headers={'Authorization':'Bearer '+token})
        if response.status_code!=200:
            raise ProductionToolError('Private Hermes preparation failed.')
        data=response.json()
    if data!={'run_id':run_id,'status':'draft_ready'}:
        raise ProductionToolError('Unexpected private Hermes preparation receipt.')


def lock_job(db,job_id):
    """Lock existing conversation before the claimed job, never claim anew."""
    from app.modules.sales_agent.models import SalesInboundJob,SalesConversation
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.engine_router import PIN_KEY,event_scope
    from app.modules.sales_crm.models import Lead
    from .bp_context import require_scoped_entities
    job=db.get(SalesInboundJob,job_id)
    if not job or job.status!='processing':
        raise ProductionToolError('The inbound job is not claimed.')
    conversation=db.query(SalesConversation).filter_by(id=job.conversation_id).populate_existing().with_for_update().one()
    job=db.query(SalesInboundJob).filter_by(id=job_id,status='processing').populate_existing().with_for_update().one_or_none()
    if not job or conversation.id!=job.conversation_id:
        raise ProductionToolError('Inbound claim changed.')
    scope=TurnScope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    db.query(Lead).filter_by(id=scope.lead_id).populate_existing().with_for_update().one()
    _,project,lead,conversation=require_scoped_entities(db,scope)
    inbound=scoped_messages_query(db,conversation).filter_by(id=job.message_id,channel=conversation.channel,direction='inbound',role='user').one_or_none()
    if not inbound or not inbound.provider_message_id or conversation.channel not in {'sms','whatsapp'} or lead.is_demo or project.is_demo:
        raise ProductionToolError('Live inbound scope is invalid.')
    meta=inbound.metadata_json or {};pin=meta.get(PIN_KEY) or {}
    if (meta.get('lead_id')!=scope.lead_id or meta.get('project_id')!=scope.project_id
            or not meta.get('continuity_recorded') or pin.get('engine')!=HERMES
            or any(pin.get(k)!=v for k,v in event_scope(conversation,f'{conversation.provider}:{inbound.provider_message_id}').items())):
        raise ProductionToolError('Authenticated Hermes event pin is missing.')
    from app.modules.sales_agent.provider_routes import assert_dispatchable
    assert_dispatchable(db,conversation)
    return job,scope,conversation,lead,inbound


async def dispatch_or_reconcile(db,scope,conversation,lead,run_id,inbound_id,plan,delivery=None):
    """Use the exact shared dispatcher once. Subsequent attempts only inspect receipts."""
    from app.modules.sales_agent.live_service import _dispatch
    existing=receipts(db,conversation,scope,plan,run_id=run_id,inbound_id=inbound_id)
    if existing:return existing
    if delivery is None:
        raise ProductionToolError('An issued plan has no outbox; original access must be reviewed.')
    # A new inbound may arrive while waiting on a prior provider receipt.
    # Only receipt reconciliation is allowed for the earlier turn.
    if run_id:
        from app.modules.sales_agent.continuity import state as continuity_state
        if continuity_state(conversation).get('last_inbound_message_id') != inbound_id:
            raise ProductionToolError('A newer inbound supersedes an unsent delivery.')
    await _dispatch(db,conversation=conversation,lead=lead,content=delivery['content'],role='assistant',
        agent_run_id=run_id,metadata=delivery['metadata'],idempotency_key=delivery['idempotency_key'])
    db.expire_all()
    result=receipts(db,conversation,scope,plan,run_id=run_id,inbound_id=inbound_id)
    if not result:raise ProductionToolError('Provider dispatcher returned no durable receipt.')
    return result


def control_delivery(db,job,scope,conversation,lead,inbound):
    """Deterministic STOP / handoff, before any SDK or model-policy requirement."""
    from app.modules.sales_agent.continuity_policy import explicit_opt_out,evidenced_pause_reason
    from app.modules.sales_agent.moderation import precheck
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.models import SalesFollowUpJob
    from app.modules.governance.services import create_intervention_case
    meta=inbound.metadata_json or {}
    existing=meta.get('hermes_control')
    stop=explicit_opt_out(inbound.content)
    severe=precheck(inbound.content) if not stop else None
    reason=(severe or {}).get('reason') or (evidenced_pause_reason(inbound.content) if not stop else None)
    if not stop and not reason:return None
    if existing:
        kind=existing.get('kind')
        if kind!=('opt_out' if stop else 'handoff') or existing.get('epoch')!=continuity.epoch(conversation):
            raise ProductionToolError('Existing deterministic control was superseded.')
    else:
        if stop:
            lead.is_opt_out=True;lead.consent_status='opted_out';lead.agent_status='paused';lead.next_action_at=None
            conversation.is_paused=True;conversation.pause_reason='Lead opted out'
            kind='opt_out'
        else:
            if lead.is_opt_out or lead.consent_status!='granted':
                raise ProductionToolError('Handoff acknowledgment is not authorized.')
            create_intervention_case(db,conversation=conversation,lead=lead,reason=reason,evidence=inbound.content)
            kind='handoff'
        # Existing takeover barrier prevents another prepared turn from sending.
        continuity.pause(db,conversation)
        db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id).filter(
            SalesFollowUpJob.status.in_(['pending','processing'])).update({SalesFollowUpJob.status:'cancelled'},synchronize_session=False)
        job.status='processing'  # this deterministic control owns the current job
        inbound.metadata_json={**(inbound.metadata_json or {}),'hermes_control':{'kind':kind,'epoch':continuity.epoch(conversation)},
                               'awaiting_resume':False,'agent_turn_status':'processing'}
        db.flush();db.commit()
    content=STOP_REPLY if kind=='opt_out' else HANDOFF_REPLY
    key='hermes:control:'+inbound.id
    return {'content':content,'idempotency_key':key,'metadata':{'engine':CONTROL_ENGINE,'control_outcome':kind,
            'lead_id':scope.lead_id,'project_id':scope.project_id,'hermes_inbound_message_id':inbound.id,
            'continuity_epoch':continuity.epoch(conversation)}}


def finish_job(db,job_id,scope,inbound_id,message_id):
    from app.modules.sales_agent.models import SalesMessage,ExternalWebhookEvent
    from app.modules.sales_agent import continuity
    job,actual,conversation,lead,inbound=lock_job(db,job_id)
    if actual!=scope or inbound.id!=inbound_id:
        raise ProductionToolError('The job changed before completion.')
    row=db.get(SalesMessage,message_id)
    if not row or row.conversation_id!=conversation.id or (row.metadata_json or {}).get('hermes_inbound_message_id')!=inbound.id:
        raise ProductionToolError('Final accepted reply missing.')
    from .production_tools import _verify_provider_receipt
    from app.modules.sales_agent.continuity import check_epoch
    check_epoch(conversation,(row.metadata_json or {}).get('continuity_epoch'))
    _verify_provider_receipt(db,row,scope,conversation.channel)
    from .resume_batch import verify_resume_batch
    from app.modules.sales_agent.models import AgentRun
    run_id=(row.metadata_json or {}).get('agent_run_id')
    run=db.get(AgentRun,run_id) if run_id else None
    sources=verify_resume_batch(db,scope,conversation,inbound,run=run)
    if not continuity.mark_handled(db,conversation,row,[source.id for source in sources]):
        raise ProductionToolError('Final message has not been accepted.')
    db.flush()
    if len(sources)>1 and not continuity.pending(db,conversation) and not conversation.is_paused:
        value=continuity.state(conversation);value['waiting_for_lead']=value.get('last_inbound_message_id')==inbound.id;conversation.continuity_json=value
    if conversation.is_paused:
        value=continuity.state(conversation);value['waiting_for_lead']=False;conversation.continuity_json=value
    job.status='processed';job.processed_at=now();job.error_code=job.error_message=None
    inbound.metadata_json={**(inbound.metadata_json or {}),'agent_turn_status':'answered','agent_turn_error':None}
    meta=inbound.metadata_json
    if meta.get('webhook_event_id'):
        event=db.query(ExternalWebhookEvent).filter_by(platform=meta.get('provider'),external_event_id=meta['webhook_event_id']).first()
        if event:event.status='processed';event.processed_at=now()
    from .scheduled_work import schedule_after_reply
    # Optional scheduling must never undo an already accepted inbound receipt.
    # Preserve failures as explicit diagnostic metadata, with no blind re-send.
    from fastapi import HTTPException
    try:
        with db.begin_nested():
            schedule_after_reply(db,scope,conversation,lead,inbound,row)
    except (ValueError, HTTPException):
        inbound.metadata_json={**(inbound.metadata_json or {}),'hermes_scheduling_status':'review'}
    db.commit()


def booking_delivery(db,scope,conversation,run,inbound,result):
    from app.modules.sales_agent.booking_models import SalesBookingOperation
    from app.modules.sales_crm.models import Meeting,MeetingStatus
    from .production_tools import _utc
    from zoneinfo import ZoneInfo
    booking=db.get(SalesBookingOperation,result['booking_operation_id']);meeting=db.get(Meeting,result['meeting_id'])
    if (not booking or not meeting or booking.meeting_id!=meeting.id or meeting.status not in {MeetingStatus.SCHEDULED,MeetingStatus.CONFIRMED}
            or any(getattr(booking,k)!=v for k,v in scope.__dict__.items()) or meeting.is_demo):
        raise ProductionToolError('Booking receipt cannot be confirmed to the lead.')
    saved=booking.snapshot_json;ctx=saved['context'];zone=ctx['timezone']
    if (_utc(meeting.meeting_time).isoformat()!=saved['option']['starts_at'] or meeting.visit_address!=ctx['location']['address']):
        raise ProductionToolError('Booking changed before confirmation.')
    local=_utc(meeting.meeting_time).astimezone(ZoneInfo(zone))
    label=ctx.get('property_type_name') or ctx.get('unit_code') or result['property_name']
    text=f'Your visit for {label} is confirmed for {local:%Y-%m-%d} at {local:%H:%M} ({zone}). Location: {meeting.visit_address}.'
    return {'content':text,'idempotency_key':'hermes:booking:'+run.id+':'+result['operation_id'],
            'metadata':{'engine':ENGINE,'agent_run_id':run.id,'lead_id':scope.lead_id,'project_id':scope.project_id,
                        'hermes_inbound_message_id':inbound.id,'continuity_epoch':run.input_snapshot['continuity_epoch'],
                        'meeting_id':meeting.id}}


async def run_job(db,job_id,*,prepare=request_sdk_draft):
    """One claimed inbound; no automatic engine fallback or provider resend."""
    require_selectable(HERMES)
    from app.modules.sales_agent.models import AgentRun
    from .live_preparation import reserve_live_run
    from .live_domain_parity import persist_contextual_preferences
    from .live_coordinator import provisional_delivery_plan,reconcile_live_reply,next_native_effect
    from .production_tools import _load_live_turn,persist_live_preferences,execute_first_live_booking
    from .bp_operation_models import HermesSalesOperation
    from .live_materials import issue_live_material_batch,complete_live_material_batch
    db.info['hermes_checkpoint']='lock_job'
    job,scope,conversation,lead,inbound=lock_job(db,job_id)
    inbound_id=inbound.id
    control=control_delivery(db,job,scope,conversation,lead,inbound)
    if control:
        canonical,plan=build_plan(control['idempotency_key'],'reply',control['content'],conversation.channel)
        control['content']=canonical
        ids=await dispatch_or_reconcile(db,scope,conversation,lead,None,inbound_id,plan,control)
        finish_job(db,job_id,scope,inbound_id,ids[-1]);return
    db.info['hermes_checkpoint']='reserve_run'
    # Existing planned executions are receipt-only on retry. Do not reserve
    # another model run, and do not require their inbound to remain latest.
    pin=(inbound.metadata_json or {}).get('sales_engine_pin') or {}
    existing=db.query(AgentRun).filter_by(event_id=pin.get('event_id'),conversation_id=scope.conversation_id).one_or_none()
    receipt_only=bool(existing and (existing.output_snapshot or {}).get('live_draft')
                      and (existing.output_snapshot or {}).get('hermes_delivery_plans'))
    run=reserve_live_run(db,scope,inbound_message_id=inbound_id,receipt_only=receipt_only);run_id=run.id
    if run.status not in {'running','completed'}:
        raise ProductionToolError('Hermes run needs staff review.')
    ready=bool((run.output_snapshot or {}).get('live_draft'))
    if not ready and run.output_snapshot:
        raise ProductionToolError('Unexpected persisted runtime state.')
    db.commit()
    if not ready:
        db.info['hermes_checkpoint']='sdk_prepare'
        await prepare(job_id,run_id)  # private SDK only, no open API transaction
    job,actual,conversation,lead,inbound=lock_job(db,job_id)
    if actual!=scope or inbound.id!=inbound_id:raise ProductionToolError('Job changed during preparation.')
    db.info['hermes_checkpoint']='restore_run'
    run=reserve_live_run(db,scope,inbound_message_id=inbound_id,receipt_only=receipt_only)
    if run.id!=run_id:raise ProductionToolError('Runtime reservation changed.')
    if run.status=='running':
        db.info['hermes_checkpoint']='reply_plan'
        delivery=provisional_delivery_plan(run,scope,inbound_id)
        delivery,plan=record_plan(db,run,conversation,delivery,kind='reply')
        db.info['hermes_checkpoint']='reply_provider_receipt'
        ids=await dispatch_or_reconcile(db,scope,conversation,lead,run_id,inbound_id,plan,None if receipt_only else delivery)
        db.info['hermes_checkpoint']='reply_state_commit'
        reconcile_live_reply(db,scope,inbound_message_id=inbound_id,run_id=run_id,outbound_message_id=ids[-1])
        db.commit()
    elif run.status!='completed':raise ProductionToolError('Runtime reservation requires review.')
    # A completed informational group is reconciled from every original
    # accepted part. Native writes deliberately require the single-part lane.
    db.expire_all();run=db.get(AgentRun,run_id)
    group_ids=((run.output_snapshot or {}).get('metadata') or {}).get('message_ids') or []
    if len(group_ids)>1:
        reconcile_live_reply(db,scope,inbound_message_id=inbound_id,run_id=run_id,outbound_message_id=group_ids[-1])
        finish_job(db,job_id,scope,inbound_id,group_ids[-1]);return
    db.info['hermes_checkpoint']='load_accepted_turn'
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_id)
    last_id=reply.id;selected=next_native_effect(receipt.state_after,inbound.id)
    if selected['preferences'] and not (run.output_snapshot or {}).get('native_live_profile'):
        db.info['hermes_checkpoint']='crm_preferences'
        if persist_contextual_preferences(db,scope,inbound_message_id=inbound_id) is None:
            persist_live_preferences(db,scope,inbound_message_id=inbound_id)
        db.flush()
    if selected['kind']=='book':
        db.info['hermes_checkpoint']='native_booking'
        result=execute_first_live_booking(db,scope,inbound_message_id=inbound_id)
        delivery=booking_delivery(db,scope,conversation,run,inbound,result)
        delivery,plan=record_plan(db,run,conversation,delivery,kind='booking',operation_id=result['operation_id'])
        # Commit reservation + receipt before provider delivery. Calendar is
        # handled asynchronously by the existing reconciler, not Hermes.
        db.commit()
        ids=await dispatch_or_reconcile(db,scope,conversation,lead,run_id,inbound_id,plan,delivery)
        last_id=ids[-1]
        db.expire_all()
        run=db.get(AgentRun,run_id)
        output=dict(run.output_snapshot or {});effect=dict(output.get('native_live_booking') or {})
        effect.update(delivery='provider_accepted',confirmation_message_id=last_id)
        output['native_live_booking']=effect;run.output_snapshot=output;db.flush();db.commit()
    elif selected['kind'] in {'cancel','reschedule'}:
        db.info['hermes_checkpoint']='native_visit_change'
        from .live_changes import execute_live_change,verified_change
        op=execute_live_change(db,scope,inbound_message_id=inbound_id)
        kind=op.operation_type;op_id=op.id
        delivery={'content':verified_change(db,scope,op),'idempotency_key':'hermes:'+kind+':'+run.id+':'+op_id,
            'metadata':{'engine':ENGINE,'agent_run_id':run.id,'lead_id':scope.lead_id,'project_id':scope.project_id,
                'hermes_inbound_message_id':inbound_id,'continuity_epoch':run.input_snapshot['continuity_epoch']}}
        delivery,plan=record_plan(db,run,conversation,delivery,kind=kind,operation_id=op_id)
        db.commit()
        ids=await dispatch_or_reconcile(db,scope,conversation,lead,run_id,inbound_id,plan,delivery)
        last_id=ids[-1];db.expire_all();run=db.get(AgentRun,run_id)
        output=dict(run.output_snapshot or {});effect=dict(output.get('native_live_change') or {})
        effect.update(delivery='provider_accepted',confirmation_message_id=last_id)
        output['native_live_change']=effect;run.output_snapshot=output;db.commit()
    elif selected['kind']=='material':
        db.info['hermes_checkpoint']='material_authorization'
        draft=(receipt.state_after.get('offered_assets') or {}).get('pending_request') or {}
        previous=db.query(HermesSalesOperation).filter_by(**scope.__dict__,request_id=draft.get('id'),
            operation_type='material',inbound_message_id=inbound_id).one_or_none()
        if previous:
            key=(previous.result_json or {}).get('group_key')
            plan=((run.output_snapshot or {}).get('hermes_delivery_plans') or {}).get(key)
            if not plan or plan.get('operation_id')!=previous.id:
                raise ProductionToolError('Issued material plan requires review.')
            delivery=None  # cannot reconstruct raw token, reconcile only
        else:
            db.info['hermes_checkpoint']='material_storage_verification'
            delivery=issue_live_material_batch(db,scope,inbound_message_id=inbound_id)
            delivery,plan=record_plan(db,run,conversation,delivery,kind='material',operation_id=delivery['operation_id'])
        ids=await dispatch_or_reconcile(db,scope,conversation,lead,run_id,inbound_id,plan,delivery)
        db.info['hermes_checkpoint']='material_delivery_receipt'
        complete_live_material_batch(db,scope,inbound_message_id=inbound_id,message_ids=ids)
        last_id=ids[-1];db.commit()
    db.info['hermes_checkpoint']='finish_job'
    finish_job(db,job_id,scope,inbound_id,last_id)


def failure_evidence(exc, checkpoint):
    """No exception text, SQL statements, message content, URLs or credentials."""
    result={'checkpoint':checkpoint or 'unknown','exception_type':type(exc).__name__,
            'locations':[{'file':PurePath(f.filename).name,'line':f.lineno}
                         for f in traceback.extract_tb(exc.__traceback__)[-6:]]}
    sqlstate=getattr(getattr(exc,'orig',None),'pgcode',None) or getattr(getattr(exc,'orig',None),'sqlstate',None)
    if isinstance(sqlstate,str) and len(sqlstate)==5 and sqlstate.isalnum():
        result['sqlstate']=sqlstate
    return result


def mark_failure(db,job_id,*,pending=False,diagnostic=None):
    """No provider retry on uncertain, rejected, partial or superseded effects."""
    from app.modules.sales_agent.models import SalesInboundJob,SalesMessage,SalesConversation
    db.rollback()
    initial=db.get(SalesInboundJob,job_id)
    if not initial:return
    db.query(SalesConversation).filter_by(id=initial.conversation_id).with_for_update().first()
    job=db.query(SalesInboundJob).filter_by(id=job_id).populate_existing().with_for_update().one_or_none()
    if not job or job.status!='processing':return
    waiting=pending and (job.attempt_number or 0)<MAX_RECEIPT_ATTEMPTS
    job.status='retry' if waiting else 'review';job.claimed_at=None
    job.scheduled_at=now()+timedelta(seconds=3 if waiting and (job.attempt_number or 0)<=3 else 30)
    job.error_code='HERMES_PROVIDER_PENDING' if waiting else 'HERMES_RECONCILIATION_REQUIRED'
    job.error_message='Waiting for the existing provider receipt.' if waiting else 'Hermes turn requires staff review; do not automatically resend.'
    if not waiting:job.processed_at=now()
    inbound=db.get(SalesMessage,job.message_id)
    if inbound:
        inbound.metadata_json={**(inbound.metadata_json or {}),'agent_turn_status':job.status,
                               'agent_turn_error':job.error_message,
                               **({'hermes_failure_diagnostic':diagnostic} if diagnostic else {})}
    db.commit()


async def process_hermes_inbound_job(job_id):
    """Normal worker callback, but unreachable until the release gate opens."""
    require_selectable(HERMES)
    from app.db.postgres import SessionLocal
    from app.modules.sales_agent.concurrency import bounded
    db=bounded(SessionLocal())
    try:
        await run_job(db,job_id)
        return True
    except ReceiptPending as exc:
        evidence=failure_evidence(exc,db.info.get('hermes_checkpoint'))
        mark_failure(db,job_id,pending=True,diagnostic=evidence);return False
    except Exception as exc:
        evidence=failure_evidence(exc,db.info.get('hermes_checkpoint'))
        logger.warning('Hermes inbound requires review: %s',evidence)
        mark_failure(db,job_id,diagnostic=evidence);return False
    finally:
        db.close()
