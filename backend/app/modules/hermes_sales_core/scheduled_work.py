"""HEI-03B.5: scoped deterministic scheduled work and original-message resume.

No new model invocation for proactive work; no artificial buyer or provider ID.
Only an untouched single authenticated pending inbound can be requeued. Mixed
or previously attempted episodes require reconciliation instead of a new send.
"""
from datetime import datetime, timedelta, timezone

from .contracts import TurnScope
from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, _verify_provider_receipt, ACCEPTED

SCHEDULED_ENGINE = 'hermes-scheduled/1'
CADENCE_REPLY = 'Would you like to continue exploring the available properties or ask a question? Reply STOP to opt out.'


class ScheduledObsolete(ProductionToolError):
    pass


class ScheduledDeferred(RuntimeError):
    def __init__(self, when):
        self.when = when


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scoped_job(db, job_id):
    from app.modules.sales_agent.models import SalesFollowUpJob, SalesConversation
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    from app.modules.sales_agent.continuity import epoch
    from app.modules.sales_agent.provider_routes import assert_dispatchable
    from app.modules.governance.models import HumanInterventionCase
    from app.modules.onboarding_versions import require_capability, active_approved
    from .bp_context import require_scoped_entities
    from .staff_config import snapshot
    from .staged_runtime import _policy
    require_selectable(HERMES)
    job = db.get(SalesFollowUpJob, job_id)
    if not job or job.status != 'processing':
        raise ScheduledObsolete('Job is not claimed.')
    conversation = db.query(SalesConversation).filter_by(id=job.conversation_id).populate_existing().with_for_update().one()
    job = db.query(SalesFollowUpJob).filter_by(id=job_id,status='processing').populate_existing().with_for_update().one_or_none()
    if not job or job.conversation_id != conversation.id:
        raise ScheduledObsolete('Claim changed.')
    scope = TurnScope(conversation.company_id, conversation.project_id, conversation.id, conversation.lead_id)
    db.query(Lead).filter_by(id=scope.lead_id).populate_existing().with_for_update().one()
    _, project, lead, conversation = require_scoped_entities(db,scope)
    data = job.payload_json or {}
    prefix = {'resume':'resume','inactivity':'inactivity','cadence':'followup'}.get(job.kind)
    if not prefix:
        raise ProductionToolError('Unsupported scheduled job.')
    pin = data.get(PIN_KEY) or {}
    if (pin.get('engine') != HERMES or not pin.get('policy_version_id') or
            any(pin.get(k)!=v for k,v in event_scope(conversation,prefix+':'+job.id).items())):
        raise ProductionToolError('Scheduled job lacks an exact Hermes pin.')
    if (data.get('lead_id')!=scope.lead_id or data.get('project_id')!=scope.project_id or
            data.get('epoch')!=epoch(conversation)):
        raise ScheduledObsolete('Opportunity or continuity epoch changed.')
    if (conversation.channel not in {'sms','whatsapp'} or lead.is_demo or project.is_demo or lead.deleted_at or
            lead.is_opt_out or lead.consent_status!='granted' or conversation.is_paused or lead.agent_status=='human_control'):
        raise ScheduledObsolete('Contact authorization is no longer active.')
    if db.query(HumanInterventionCase).filter_by(**scope.__dict__,status='open').first():
        raise ScheduledObsolete('An open intervention owns the conversation.')
    if not active_approved(project.profile):
        raise ScheduledObsolete('Project is no longer approved.')
    require_capability(project.profile)
    assert_dispatchable(db,conversation)
    current=snapshot(db)
    if not current['configuration'].get('enabled') or (current.get('engine_selection') or {}).get('active_sales_engine')!=HERMES:
        raise ScheduledObsolete('Hermes is not enabled.')
    _policy(db,pin['policy_version_id'])
    return job,scope,conversation,lead,project


def resume_original(db, job, scope, conversation):
    """Release an untouched original inbound into the existing FIFO worker."""
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.models import AgentRun, SalesInboundJob, SalesMessage, OutboundMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    from app.modules.sales_agent.continuity_policy import explicit_opt_out, evidenced_pause_reason
    from app.modules.sales_agent.moderation import precheck
    data=job.payload_json or {}
    inputs=continuity.pending(db,conversation)
    if [m.id for m in inputs]!=data.get('input_message_ids'):
        raise ScheduledObsolete('Pending set changed; a new resume episode is required.')
    if not inputs:
        raise ScheduledObsolete('No pending inbound remains.')
    if len(inputs)!=1 or data.get('context_message_id'):
        raise ProductionToolError('Multi-input or derived resume needs explicit reconciliation.')
    inbound=inputs[0];meta=inbound.metadata_json or {}
    if (inbound.id!=continuity.state(conversation).get('last_inbound_message_id') or not inbound.provider_message_id or
            inbound.channel!=conversation.channel or inbound.status not in {'received','processed'} or
            meta.get('lead_id')!=scope.lead_id or meta.get('project_id')!=scope.project_id or
            not meta.get('continuity_recorded') or not meta.get('awaiting_resume') or meta.get('handled_by_message_id') or
            meta.get('resume_context') or meta.get('hermes_control')):
        raise ProductionToolError('Original pending inbound cannot be safely requeued.')
    if explicit_opt_out(inbound.content) or evidenced_pause_reason(inbound.content) or precheck(inbound.content):
        raise ProductionToolError('Pending control requires staff reconciliation before resume.')
    event=f'{conversation.provider}:{inbound.provider_message_id}'
    if db.query(AgentRun).filter_by(event_id=event).first() or db.query(AgentRun).filter_by(event_id='resume:'+job.id).first():
        raise ProductionToolError('Original event already has an execution; do not reinterpret it.')
    # Reject any earlier response/outbox after this inbound, even if unhandled.
    # Human failed replies and unknown provider receipts may have reached the lead.
    q=scoped_messages_query(db,conversation)
    from sqlalchemy import or_,and_
    if q.filter(SalesMessage.direction=='outbound',or_(SalesMessage.created_at>inbound.created_at,
            and_(SalesMessage.created_at==inbound.created_at,SalesMessage.id>inbound.id))).first():
        raise ProductionToolError('An intervening outbound requires review.')
    if db.query(OutboundMessage).filter(OutboundMessage.conversation_id==conversation.id,
            OutboundMessage.created_at>=inbound.created_at).first():
        raise ProductionToolError('An existing outbox requires review.')
    original=db.query(SalesInboundJob).filter_by(conversation_id=conversation.id,message_id=inbound.id).populate_existing().with_for_update().one_or_none()
    if original is not None and original.status!='awaiting_resume':
        raise ProductionToolError('Original inbound is not waiting for explicit resume.')
    if db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==conversation.id,
            SalesInboundJob.message_id!=inbound.id,SalesInboundJob.status.in_(['pending','retry','processing','review','failed'])).first():
        raise ProductionToolError('Another inbound requires reconciliation.')
    pinned=meta.get(PIN_KEY)
    candidate={**event_scope(conversation,event),'engine':HERMES,'policy_version_id':data[PIN_KEY]['policy_version_id']}
    if pinned is not None:
        if any(pinned.get(k)!=v for k,v in candidate.items() if k!='policy_version_id') or not pinned.get('policy_version_id'):
            raise ProductionToolError('Original event belongs to another engine or scope.')
        from .staged_runtime import _policy
        _policy(db,pinned['policy_version_id']);candidate=pinned
    inbound.metadata_json={**meta,PIN_KEY:candidate,'awaiting_resume':False,'agent_turn_status':'pending',
        'agent_turn_error':None,'hermes_resume_job_id':job.id}
    if original is None:
        # The authenticated webhook deliberately leaves paused inputs without
        # inbound jobs. Requeue the existing message, never mint another ID.
        original=SalesInboundJob(conversation_id=conversation.id,message_id=inbound.id,attempt_number=0)
        db.add(original)
    original.status='pending';original.claimed_at=None;original.processed_at=None;original.scheduled_at=now()
    original.error_code=original.error_message=None
    db.flush()
    job.status='processed';job.reason='hermes_resume_requeued';job.processed_at=now()
    job.payload_json={**data,'requeued_inbound_job_id':original.id,'requeued_message_id':inbound.id}
    db.commit()


def invalidate_boundary(state, latest, conversation):
    """Discard transient authorization across takeover or non-Hermes responses.

    Preserve buyer preferences and property focus, never a stale offer/recap.
    Executed commercial effects remain in immutable operation receipts.
    """
    from app.modules.sales_agent.continuity import epoch,state as continuity_state
    meta=(latest.metadata_json or {}) if latest else {}
    if latest and meta.get('engine')=='hermes-agent' and meta.get('continuity_epoch')==epoch(conversation):
        return False
    if not continuity_state(conversation).get('offer_barrier') and not latest:
        return False
    state.update(last_presented_choice_set=None,choice_set_initialized=True,last_presented_units=[],
                 last_slot_search=None,booking_proposal=None,confirmation_request=None,offered_assets={})
    draft=state.get('visit_draft') or {}
    if draft.get('status') not in {'confirmed','cancelled','rescheduled','committed'}:
        state['visit_draft']={'unit_id':None,'date':None,'start_time':None,'status':'idle'}
    return True


def _no_active_visit(db, scope):
    from app.modules.sales_agent.first_booking import active_meetings
    return not active_meetings(db,scope,now())


def schedule_after_reply(db, scope, conversation, lead, inbound, row):
    """Schedule at most one inactivity close and one cadence per answered turn.

    Use existing Staff cadence settings and governance windows. No recursive
    cadence loop; new genuine buyer activity supersedes the old episode.
    """
    from app.modules.sales_agent import continuity
    from app.modules.sales_agent.models import SalesFollowUpJob
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.projects.models import Project
    from app.modules.sales_crm.scheduling import next_cadence_time
    from app.modules.governance.services import next_allowed_proactive_time
    from app.modules.sales_agent.engine_router import PIN_KEY, event_scope
    from .staff_config import snapshot
    from uuid import uuid4
    policy=snapshot(db)
    if not policy['configuration'].get('enabled') or (policy.get('engine_selection') or {}).get('active_sales_engine')!=HERMES or not policy.get('published_version_id'):
        return
    if (conversation.is_paused or lead.is_opt_out or lead.consent_status!='granted' or
            lead.agent_status=='human_control' or not continuity.state(conversation).get('waiting_for_lead') or
            (row.metadata_json or {}).get('engine')!='hermes-agent' or not _no_active_visit(db,scope)):
        return
    current=continuity.state(conversation)
    if current.get('last_inbound_message_id')!=inbound.id or current.get('last_response_message_id')!=row.id:
        return
    config=db.query(AIConfiguration).filter_by(company_id=None).first()
    cadence=(config.agent_ventas or {}).get('cadence_config') or {} if config else {}
    minutes=int(cadence.get('inactivity_minutes',45))
    hours=int(cadence.get({'hot':'hot_hours','warm':'warm_hours','cold':'cold_hours'}.get(lead.intent_tier,'warm_hours'),
                         {'hot':24,'warm':72,'cold':336}.get(lead.intent_tier,72)))
    if not 1<=minutes<=1440 or not 1<=hours<=8760:
        return  # malformed staff timing never causes immediate/unbounded messaging
    project=db.get(Project,scope.project_id)
    due=next_cadence_time(now=now(),timezone_name=project.timezone or 'UTC',delay_hours=hours)
    due=max(due,next_allowed_proactive_time(db,company_id=scope.company_id,project_id=scope.project_id,now=due))
    base={'lead_id':scope.lead_id,'project_id':scope.project_id,'epoch':current['epoch'],
          'inbound_message_id':inbound.id,'response_message_id':row.id,'hermes_scheduled':True}
    # Cancel old unclaimed schedules only. A claimed job is revalidated at send.
    for old in db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').filter(
            SalesFollowUpJob.kind.in_(['inactivity','cadence'])).all():
        if (old.payload_json or {}).get('response_message_id')!=row.id:
            old.status='cancelled';old.processed_at=now()
    for kind,when,expiry in [('inactivity',row.created_at+timedelta(minutes=minutes),row.created_at+timedelta(minutes=minutes+15)),
                              ('cadence',due,due+timedelta(hours=24))]:
        if expiry<=now():continue
        key=f'hermes:{kind}:{conversation.id}:{row.id}:{current["epoch"]}'
        if db.query(SalesFollowUpJob).filter_by(idempotency_key=key).first():continue
        job_id=str(uuid4());event=('inactivity:' if kind=='inactivity' else 'followup:')+job_id
        pin={**event_scope(conversation,event),'engine':HERMES,'policy_version_id':policy['published_version_id']}
        db.add(SalesFollowUpJob(id=job_id,conversation_id=conversation.id,kind=kind,status='pending',
               reason='conversation_inactivity' if kind=='inactivity' else f'{lead.intent_tier}_cadence',
               scheduled_at=when,idempotency_key=key,payload_json={**base,'expires_at':expiry.isoformat(),PIN_KEY:pin}))
    lead.next_action_at=due
    db.flush()


def scheduled_plan(db, job, scope, conversation, lead, project, *, check_window=True):
    from app.modules.sales_agent import continuity, live_service
    from app.modules.sales_agent.models import SalesInboundJob, SalesMessage, AgentRun
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.governance.services import next_allowed_proactive_time
    from app.modules.sales_agent.sales_policy import policy_context,compliance_action_holds
    from app.modules.sales_agent.commercial_context import confirmed_profile_facts
    data=job.payload_json or {};value=continuity.state(conversation)
    if job.kind not in {'inactivity','cadence'} or not data.get('hermes_scheduled'):
        raise ProductionToolError('Unscoped legacy cadence must not be inherited automatically.')
    if not value.get('waiting_for_lead') or data.get('inbound_message_id')!=value.get('last_inbound_message_id') or data.get('response_message_id')!=value.get('last_response_message_id'):
        raise ScheduledObsolete('New conversation activity superseded the scheduled episode.')
    if continuity.pending(db,conversation) or db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==conversation.id,
            SalesInboundJob.status.in_(['pending','retry','processing','failed','review','awaiting_resume'])).first():
        raise ScheduledObsolete('Unresolved buyer input takes priority.')
    if not _no_active_visit(db,scope):raise ScheduledObsolete('An active appointment stops proactive messages.')
    if compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile))):
        raise ScheduledObsolete('Commercial restrictions block proactive messages.')
    if job.kind=='inactivity' and value.get('closed_response_message_id')==data.get('response_message_id'):
        raise ScheduledObsolete('This episode was already closed.')
    if check_window and job.scheduled_at>now():raise ScheduledDeferred(job.scheduled_at)
    if check_window and now()>datetime.fromisoformat(data['expires_at']):raise ScheduledObsolete('Scheduled contact expired.')
    q=scoped_messages_query(db,conversation)
    row=q.filter_by(id=data.get('response_message_id')).one_or_none()
    inbound=q.filter_by(id=data.get('inbound_message_id'),direction='inbound',role='user',channel=conversation.channel).one_or_none()
    out=_verify_provider_receipt(db,row,scope,conversation.channel)
    run=db.get(AgentRun,out.agent_run_id) if out.agent_run_id else None
    if (not run or run.status!='completed' or run.graph_version!='hermes/live/1' or run.conversation_id!=scope.conversation_id
            or (row.metadata_json or {}).get('agent_run_id')!=run.id or (run.input_snapshot or {}).get('message_id')!=data.get('inbound_message_id')):
        raise ProductionToolError('Scheduled source does not identify a completed Hermes run.')
    if (not inbound or not inbound.provider_message_id or (inbound.metadata_json or {}).get('handled_by_message_id')!=row.id or
            (row.metadata_json or {}).get('engine')!='hermes-agent' or (row.metadata_json or {}).get('continuity_epoch')!=value['epoch']):
        raise ScheduledObsolete('Source response no longer belongs to this episode.')
    if check_window:
        allowed=next_allowed_proactive_time(db,company_id=scope.company_id,project_id=scope.project_id,now=now())
        if allowed>now():
            if job.kind=='cadence' and allowed<datetime.fromisoformat(data['expires_at']):raise ScheduledDeferred(allowed)
            raise ScheduledObsolete('Outside proactive contact window.')
        if conversation.channel=='whatsapp' and not live_service._whatsapp_customer_window_open(db,conversation):
            raise ScheduledObsolete('WhatsApp customer window closed.')
    key='hermes:scheduled:'+job.id
    text=continuity.CLOSING if job.kind=='inactivity' else CADENCE_REPLY
    from app.modules.sales_agent.response_policy import render_channel_text
    text=render_channel_text(text,conversation.channel)
    return text,key,{'engine':SCHEDULED_ENGINE,'hermes_scheduled_job_id':job.id,'lead_id':scope.lead_id,
                     'project_id':scope.project_id,'continuity_epoch':value['epoch'],
                     'hermes_inbound_message_id':inbound.id,'event_kind':'hermes_'+job.kind}


def authorize_scheduled(db,conversation,lead,metadata,content,key,agent_run_id):
    """Same twice-checked dispatcher boundary; no fabricated AgentRun."""
    if agent_run_id is not None:raise ProductionToolError('Scheduled work has no model run.')
    job,scope,current,fresh,project=scoped_job(db,metadata.get('hermes_scheduled_job_id'))
    text,expected,meta=scheduled_plan(db,job,scope,current,fresh,project)
    if (current.id!=conversation.id or fresh.id!=lead.id or key!=expected or content!=text or
            any(metadata.get(k)!=v for k,v in meta.items()) or metadata.get('sales_asset_share_ids') or
            metadata.get('delivery_group')!={'key':key,'part':1,'total':1}):
        raise ProductionToolError('Scheduled message differs from the authorized episode.')


def existing_receipt(db, job, scope, conversation, text, key, meta):
    from app.modules.sales_agent.models import OutboundMessage,SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from .provider_delivery import ReceiptPending
    out=db.query(OutboundMessage).filter_by(idempotency_key=key).one_or_none()
    if not out:return None
    rows=scoped_messages_query(db,conversation).filter_by(direction='outbound',role='assistant',channel=conversation.channel).filter(
        SalesMessage.metadata_json['outbound_message_id'].as_string()==out.id).all()
    if len(rows)!=1:raise ProductionToolError('Scheduled outbox has no unique message.')
    row=rows[0];m=row.metadata_json or {}
    if (out.conversation_id!=conversation.id or out.channel!=conversation.channel or out.provider!=conversation.provider or out.agent_run_id is not None or
            row.content!=text or out.content!=text or not out.provider_message_id or row.provider_message_id!=out.provider_message_id or
            any(m.get(k)!=v for k,v in meta.items()) or m.get('delivery_group')!={'key':key,'part':1,'total':1}):
        raise ProductionToolError('Scheduled delivery receipt is inconsistent; no resend.')
    if row.status not in ACCEPTED|{'queued','sending','scheduled'} or out.status not in ACCEPTED|{'queued','sending','scheduled'}:
        raise ProductionToolError('Scheduled delivery requires reconciliation.')
    if row.status not in ACCEPTED or out.status not in ACCEPTED:raise ReceiptPending('Waiting for scheduled provider receipt.')
    _verify_provider_receipt(db,row,scope,conversation.channel)
    return row


async def run_scheduled(db,job_id):
    from app.modules.sales_agent.live_service import _dispatch
    from app.modules.sales_agent import continuity
    job,scope,conversation,lead,project=scoped_job(db,job_id)
    if job.kind=='resume':return resume_original(db,job,scope,conversation)
    # Reconcile an existing send without requiring the old contact window to
    # remain open; no new provider call is permitted on that path.
    text,key,meta=scheduled_plan(db,job,scope,conversation,lead,project,check_window=False)
    row=existing_receipt(db,job,scope,conversation,text,key,meta)
    if row is None:
        scheduled_plan(db,job,scope,conversation,lead,project)
        await _dispatch(db,conversation=conversation,lead=lead,content=text,role='assistant',agent_run_id=None,
                        metadata=meta,idempotency_key=key)
        db.expire_all()
        job,scope,conversation,lead,project=scoped_job(db,job_id)
        text,key,meta=scheduled_plan(db,job,scope,conversation,lead,project,check_window=False)
        row=existing_receipt(db,job,scope,conversation,text,key,meta)
        if row is None:raise ProductionToolError('Provider did not return a durable receipt.')
    job.status='processed';job.processed_at=now()
    job.payload_json={**job.payload_json,'receipt_message_id':row.id}
    if job.kind=='inactivity':
        value=continuity.state(conversation);value.update(last_closing_message_id=row.id,closed_response_message_id=job.payload_json['response_message_id']);conversation.continuity_json=value
    else:lead.next_action_at=None
    lead.last_interaction_at=now();db.commit()


async def process_hermes_scheduled_job(job_id):
    from app.db.postgres import SessionLocal
    from app.modules.sales_agent.concurrency import bounded
    from app.modules.sales_agent.models import SalesFollowUpJob,SalesConversation,OutboundMessage
    from .provider_delivery import ReceiptPending
    require_selectable(HERMES)
    db=bounded(SessionLocal())
    try:
        await run_scheduled(db,job_id);return True
    except Exception as exc:
        db.rollback()
        job=db.get(SalesFollowUpJob,job_id)
        if job:
            db.query(SalesConversation).filter_by(id=job.conversation_id).with_for_update().first()
            job=db.query(SalesFollowUpJob).filter_by(id=job_id).populate_existing().with_for_update().one_or_none()
        if job and job.status=='processing':
            if isinstance(exc,ScheduledDeferred):
                job.status='pending';job.scheduled_at=exc.when
            elif isinstance(exc,ReceiptPending) and (job.attempt_number or 0)<10:
                job.status='pending';job.scheduled_at=now()+timedelta(seconds=30);job.attempt_number=(job.attempt_number or 0)+1
            elif isinstance(exc,ScheduledObsolete) and not db.query(OutboundMessage).filter_by(idempotency_key='hermes:scheduled:'+job.id).first():
                job.status='cancelled';job.processed_at=now();job.reason='hermes_episode_superseded'
            else:
                job.status='review';job.processed_at=now();job.reason='hermes_scheduled_reconciliation_required'
            job.claimed_at=None;db.commit()
        return False
    finally:db.close()
