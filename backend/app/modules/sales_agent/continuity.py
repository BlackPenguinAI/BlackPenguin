"""Scoped message receipts, takeover barriers and durable conversation episodes.

All mutations run under the conversation lock. IDs bind receipts and job inputs;
wall-clock ordering alone never means a lead message was answered.
"""
from datetime import datetime,timedelta
import uuid
from sqlalchemy import or_
from .models import SalesConversation,SalesMessage,SalesInboundJob,SalesFollowUpJob,AgentRun
from .conversation_scope import scoped_messages_query
from .execution import now as clock,permitted

ACCEPTED={'sent','delivered','read','accepted','queued','sending','scheduled'}
CLOSING="I'll be here if any other questions come up. Just message me whenever you're ready. Take care!"


def state(conversation):
    value=dict(conversation.continuity_json or {})
    if value.get('lead_id')!=conversation.lead_id or value.get('project_id')!=conversation.project_id:
        return {'epoch':int(value.get('epoch',0))+1,'lead_id':conversation.lead_id,'project_id':conversation.project_id}
    return value


def epoch(conversation):return state(conversation)['epoch']


def accepted(message):
    return bool(message and message.status in ACCEPTED and (message.status in {'sent','delivered','read'} or message.provider_message_id))


def cancel_jobs(db,conversation,*,kinds=('resume','inactivity')):
    for job in db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id==conversation.id,
        SalesFollowUpJob.kind.in_(kinds),SalesFollowUpJob.status.in_(['pending','processing'])).all():
        job.status='cancelled';job.processed_at=clock(datetime)


def clear_offers(db,conversation,event):
    from .dialogue_store import Scope,load,save
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    revision,value=load(db,scope)
    value.offers=[];value.booking_proposal=None;value.reschedule_proposal=None;value.cancellation_proposal=None
    value.booking_search={};value.reschedule_search={};value.cancellation_search={}
    value.change_proposals=[]
    # A material offer lives in outbound metadata; the epoch boundary below
    # makes that metadata unavailable to an assent after takeover.
    save(db,scope,event_key=event,expected_revision=revision,state=value,metadata={'continuity_boundary':True,'epoch':epoch(conversation)})
    conversation.pending_asset_id=None;conversation.pending_asset_offered_at=None


def pending(db,conversation):
    result=[]
    for m in scoped_messages_query(db,conversation).filter_by(direction='inbound',role='user').filter(or_(
        SalesMessage.metadata_json['awaiting_resume'].as_boolean().is_(True),
        SalesMessage.metadata_json['handled_by_role'].as_string()=='human')).order_by(SalesMessage.created_at,SalesMessage.id).all():
        meta=m.metadata_json or {}
        if meta.get('resume_context'):continue
        response=scoped_messages_query(db,conversation).filter_by(id=meta['handled_by_message_id']).first() if meta.get('handled_by_message_id') else None
        failed_manual=bool(response and response.role=='human' and response.status in {'failed','undelivered','delivery_failed','sending_failed'})
        if failed_manual or meta.get('awaiting_resume') and not meta.get('handled_by_message_id'):result.append(m)
    return result


def pause(db,conversation):
    value=state(conversation);value.update(epoch=value['epoch']+1,waiting_for_lead=False,offer_barrier=True)
    conversation.continuity_json=value
    cancel_jobs(db,conversation)
    for job in db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==conversation.id,
        SalesInboundJob.status.in_(['pending','retry','processing'])).all():
        message=scoped_messages_query(db,conversation).filter_by(id=job.message_id).first()
        if message and not (message.metadata_json or {}).get('handled_by_message_id'):
            message.metadata_json={**(message.metadata_json or {}),'awaiting_resume':True,'agent_turn_status':'awaiting_resume'}
            job.status='awaiting_resume'
    clear_offers(db,conversation,'takeover:'+str(uuid.uuid4()))


def received(db,conversation,message):
    """Called atomically with authenticated provider message persistence."""
    message.metadata_json={**(message.metadata_json or {}),'continuity_recorded':True}
    cancel_jobs(db,conversation,kinds=('inactivity',))
    value=state(conversation);value.update(last_inbound_message_id=message.id,waiting_for_lead=False)
    conversation.continuity_json=value
    continuation=db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id==conversation.id,
        SalesFollowUpJob.kind=='resume',SalesFollowUpJob.status.in_(['pending','processing'])).first()
    if conversation.is_paused or continuation:
        message.metadata_json={**(message.metadata_json or {}),'awaiting_resume':True,'agent_turn_status':'awaiting_resume'}
        if continuation and not conversation.is_paused:
            queue_resume(db,conversation)
        return False
    return True


def mark_handled(db,conversation,message,inputs):
    if not accepted(message):return False
    conversation=db.query(SalesConversation).filter_by(id=conversation.id).populate_existing().with_for_update().one()
    for identifier in inputs:
        row=scoped_messages_query(db,conversation).filter_by(id=identifier,direction='inbound',role='user').first()
        if row:
            row.metadata_json={**(row.metadata_json or {}),'handled_by_message_id':message.id,'handled_by_role':message.role,'awaiting_resume':False,'agent_turn_status':'answered'}
            for job in db.query(SalesInboundJob).filter_by(message_id=row.id).all():
                if job.status in {'awaiting_resume','pending','retry'}:job.status='superseded';job.processed_at=clock(datetime)
    message.metadata_json={**(message.metadata_json or {}),'handled_inbound_message_ids':inputs}
    value=state(conversation);value.update(last_response_message_id=message.id,waiting_for_lead=value.get('last_inbound_message_id') in inputs and not bool(pending(db,conversation)))
    conversation.continuity_json=value
    return True


def manual_accepted(db,conversation,message,inputs):
    if not mark_handled(db,conversation,message,inputs):return
    value=state(conversation);value['last_manual_message_id']=message.id;conversation.continuity_json=value
    clear_offers(db,conversation,'manual-boundary:'+message.id)


def queue_resume(db,conversation):
    cancel_jobs(db,conversation)
    value=state(conversation);value.update(epoch=value['epoch']+1,waiting_for_lead=False,offer_barrier=True)
    conversation.continuity_json=value
    inputs=pending(db,conversation)
    clear_offers(db,conversation,'resume-boundary:'+str(uuid.uuid4()))
    if not inputs:return None
    job=SalesFollowUpJob(conversation_id=conversation.id,kind='resume',reason='explicit_resume',status='pending',
        scheduled_at=clock(datetime),idempotency_key=f"continuation:{conversation.id}:{value['epoch']}",
        payload_json={'epoch':value['epoch'],'lead_id':conversation.lead_id,'project_id':conversation.project_id,'input_message_ids':[m.id for m in inputs]})
    db.add(job);return job


def resume(db,conversation):
    job=queue_resume(db,conversation)
    if not job:
        value=state(conversation);value['waiting_for_lead']=True;conversation.continuity_json=value
        response=scoped_messages_query(db,conversation).filter_by(id=value.get('last_response_message_id')).first()
        if response and accepted(response):schedule_inactivity(db,conversation,response)
    return job


def check_epoch(conversation,expected):
    if expected is not None and expected!=epoch(conversation):raise PermissionError('Conversation control changed; this response was superseded.')


def schedule_inactivity(db,conversation,message):
    from .first_booking import cadence_stopped
    if conversation.is_paused or not accepted(message) or cadence_stopped(db,conversation):return None
    # Only real exchanges, not first-contact templates or nurture campaigns.
    if (message.metadata_json or {}).get('event_kind') in {'meta_lead_first_contact','manual_lead_first_contact'}:return None
    value=state(conversation)
    if not value.get('last_inbound_message_id') or not value.get('waiting_for_lead') or value.get('closed_response_message_id')==message.id:return None
    from app.modules.ai_core.models import AIConfiguration
    config=db.query(AIConfiguration).filter_by(company_id=None).first()
    cadence=(config.agent_ventas or {}).get('cadence_config') or {} if config else {}
    minutes=int(cadence.get('inactivity_minutes',45))
    cancel_jobs(db,conversation,kinds=('inactivity',))
    key=f'inactivity:{conversation.id}:{message.id}:{epoch(conversation)}'
    if db.query(SalesFollowUpJob).filter_by(idempotency_key=key).first():return None
    due=message.created_at+timedelta(minutes=minutes)
    if due+timedelta(minutes=15)<=clock(datetime):return None
    job=SalesFollowUpJob(conversation_id=conversation.id,kind='inactivity',reason='conversation_inactivity',status='pending',scheduled_at=due,idempotency_key=key,
        payload_json={'epoch':epoch(conversation),'lead_id':conversation.lead_id,'project_id':conversation.project_id,
                      'response_message_id':message.id,'inbound_message_id':value['last_inbound_message_id'],'expires_at':(due+timedelta(minutes=15)).isoformat()})
    db.add(job);return job


def snapshot(db,conversation):
    value=state(conversation);inputs=pending(db,conversation)
    jobs=db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id==conversation.id,
        SalesFollowUpJob.kind.in_(['resume','inactivity']),SalesFollowUpJob.status.in_(['pending','processing','review'])).all()
    jobs=[j for j in jobs if (j.payload_json or {}).get('lead_id')==conversation.lead_id and (j.payload_json or {}).get('project_id')==conversation.project_id]
    return {'pending_message_count':len(inputs),'waiting_for_lead':bool(value.get('waiting_for_lead')),
        'last_response_message_id':value.get('last_response_message_id'),'last_manual_message_id':value.get('last_manual_message_id'),
        'jobs':[{'kind':j.kind,'status':j.status,'reason':j.reason,'scheduled_at':j.scheduled_at} for j in jobs]}


async def process(db,job):
    from app.modules.sales_crm.models import Lead
    from . import live_service as live
    conversation=db.query(SalesConversation).filter_by(id=job.conversation_id).populate_existing().with_for_update().one()
    data=job.payload_json or {};value=state(conversation)
    lead=db.get(Lead,conversation.lead_id)
    if (data.get('lead_id'),data.get('project_id'),data.get('epoch'))!=(conversation.lead_id,conversation.project_id,value['epoch']) or conversation.is_paused or not lead or lead.is_opt_out or not permitted(lead) or lead.deleted_at:
        job.status='cancelled';db.commit();return
    if job.kind=='resume':
        inputs=pending(db,conversation)
        if [m.id for m in inputs]!=data.get('input_message_ids'):
            job.status='cancelled';queue_resume(db,conversation);db.commit();return
        # The immutable context is a derived work item, never a provider message.
        message=db.get(SalesMessage,data.get('context_message_id')) if data.get('context_message_id') else None
        if not message:
            content='\n\n'.join(m.content for m in inputs)
            if not content or len(content.encode())>12000:
                job.status='review';job.reason='resume_context_requires_review';db.commit();return
            message=SalesMessage(conversation_id=conversation.id,channel=conversation.channel,direction='inbound',role='user',content=content,status='internal',created_at=clock(datetime),
                metadata_json={'resume_context':True,'source_message_ids':[m.id for m in inputs],'lead_id':lead.id,'project_id':conversation.project_id,'continuity_epoch':value['epoch']})
            db.add(message);db.flush();job.payload_json={**data,'context_message_id':message.id};db.commit()
        from .active_service import maybe_process_active
        await maybe_process_active(db,conversation,message,event_id_override='resume:'+job.id)
        db.refresh(job)
        if job.status!='processing':return
        run=db.query(AgentRun).filter_by(event_id='resume:'+job.id).first()
        job.status='processed' if run and run.status=='completed' and not run.error_code else 'review'
        if job.status=='review':job.reason='resume_'+(run.error_code or 'response_not_confirmed')[:100] if run else 'resume_response_not_confirmed'
    else:
        from .first_booking import cadence_stopped
        if cadence_stopped(db,conversation) or data.get('inbound_message_id')!=value.get('last_inbound_message_id') or data.get('response_message_id')!=value.get('last_response_message_id') or pending(db,conversation):
            job.status='cancelled';db.commit();return
        waiting=db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==conversation.id,SalesInboundJob.status.in_(['pending','retry','processing','failed'])).first()
        response=db.get(SalesMessage,data.get('response_message_id'))
        if waiting or not accepted(response) or clock(datetime)>datetime.fromisoformat(data['expires_at']):
            job.status='cancelled';db.commit();return
        from app.modules.governance.services import next_allowed_proactive_time
        if next_allowed_proactive_time(db,company_id=conversation.company_id,project_id=conversation.project_id,now=clock(datetime))>clock(datetime):
            job.status='cancelled';db.commit();return
        if conversation.channel=='whatsapp' and not live._whatsapp_customer_window_open(db,conversation):
            job.status='cancelled';db.commit();return
        from .dialogue_store import Scope
        from .active_service import selected_policy
        if not selected_policy(db,Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)):
            job.status='cancelled';db.commit();return
        from app.modules.projects.models import Project
        from app.modules.onboarding_versions import require_capability
        from .execution import simulated
        project=db.get(Project,conversation.project_id)
        if not project or (project.is_demo or lead.is_demo) and not simulated(conversation):
            job.status='cancelled';db.commit();return
        try:
            if project.profile:require_capability(project.profile)
        except Exception:
            job.status='cancelled';db.commit();return
        sent=await live._dispatch(db,conversation=conversation,lead=lead,content=CLOSING,role='assistant',agent_run_id=None,
            metadata={'event_kind':'inactivity_closing','continuity_epoch':value['epoch'],'inactivity_job_id':job.id},idempotency_key='closing:'+job.id)
        job.status='processed' if accepted(sent) else 'review'
        if job.status=='processed':
            value=state(conversation);value.update(waiting_for_lead=True,last_closing_message_id=sent.id,closed_response_message_id=data['response_message_id']);conversation.continuity_json=value
    job.processed_at=clock(datetime);db.commit()
