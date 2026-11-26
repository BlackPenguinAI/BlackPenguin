"""Bounded recovery of untouched provider messages; no synthetic inbound.

The latest genuine message owns the run. Earlier messages are included as
verified history and are marked handled only after the accepted final reply.
Any previous run/outbox or change of opportunity requires manual reconciliation.
"""
from __future__ import annotations
from hashlib import sha256
from .production_tools import ProductionToolError

MAX_INPUTS = 10
MAX_BYTES = 12000


def input_hash(row):
    return sha256(row.content.encode('utf-8')).hexdigest()


def bind_inputs(db, scope, conversation, inputs, *, policy_version_id, resume_job_id):
    from app.modules.sales_agent.models import AgentRun, SalesInboundJob, SalesMessage, OutboundMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.engine_router import event_scope, PIN_KEY
    from app.modules.sales_agent.continuity import epoch, state
    from app.modules.sales_agent.continuity_policy import explicit_opt_out, evidenced_pause_reason
    from app.modules.sales_agent.moderation import precheck
    from .staged_runtime import _policy
    from sqlalchemy import or_, and_
    if not 1 <= len(inputs) <= MAX_INPUTS or len({r.id for r in inputs}) != len(inputs):
        raise ProductionToolError('Resume input count is outside the supported bound.')
    if inputs[-1].id != state(conversation).get('last_inbound_message_id'):
        raise ProductionToolError('Resume must end at the latest authenticated inbound.')
    if any(not isinstance(r.content,str) or not r.content.strip() or len(r.content)>4000 for r in inputs) or sum(len(r.content.encode('utf-8')) for r in inputs)>MAX_BYTES:
        raise ProductionToolError('Resume context exceeds its safe history bound.')
    ids=[r.id for r in inputs]
    first=inputs[0]
    q=scoped_messages_query(db,conversation)
    later=q.filter(or_(SalesMessage.created_at>first.created_at,and_(SalesMessage.created_at==first.created_at,SalesMessage.id>=first.id))).order_by(SalesMessage.created_at,SalesMessage.id).all()
    if [r.id for r in later]!=ids or db.query(OutboundMessage).filter(OutboundMessage.conversation_id==conversation.id,OutboundMessage.created_at>=first.created_at).first():
        raise ProductionToolError('Intervening dialogue or provider outbox requires review.')
    if db.query(AgentRun).filter_by(event_id='resume:'+resume_job_id).first():
        raise ProductionToolError('Derived resume event already has an execution.')
    if db.query(SalesInboundJob).filter(SalesInboundJob.conversation_id==conversation.id,~SalesInboundJob.message_id.in_(ids),SalesInboundJob.status.in_(['pending','retry','processing','review','failed'])).first():
        raise ProductionToolError('Another inbound requires reconciliation.')
    bindings=[]
    for row in inputs:
        meta=row.metadata_json or {}
        if (row.direction!='inbound' or row.role!='user' or row.channel!=conversation.channel or not row.provider_message_id
                or row.status not in {'received','processed'} or meta.get('lead_id')!=scope.lead_id or meta.get('project_id')!=scope.project_id
                or not meta.get('continuity_recorded') or not meta.get('awaiting_resume') or meta.get('handled_by_message_id')
                or meta.get('resume_context') or meta.get('hermes_control') or meta.get('hermes_resume_batch')):
            raise ProductionToolError('Original pending input cannot be safely requeued.')
        if explicit_opt_out(row.content) or evidenced_pause_reason(row.content) or precheck(row.content):
            raise ProductionToolError('Pending control requires staff reconciliation.')
        event=f'{conversation.provider}:{row.provider_message_id}'
        if db.query(AgentRun).filter_by(event_id=event).first():
            raise ProductionToolError('An original event already has an execution.')
        job=db.query(SalesInboundJob).filter_by(conversation_id=conversation.id,message_id=row.id).populate_existing().with_for_update().one_or_none()
        if job is not None and job.status!='awaiting_resume':
            raise ProductionToolError('An original input is not waiting for resume.')
        pin={**event_scope(conversation,event),'engine':'hermes','policy_version_id':policy_version_id}
        prior=meta.get(PIN_KEY)
        if prior is not None:
            if any(prior.get(k)!=v for k,v in pin.items() if k!='policy_version_id') or not prior.get('policy_version_id'):
                raise ProductionToolError('Original input belongs to another engine or scope.')
            _policy(db,prior['policy_version_id']);pin=prior
        bindings.append((row,job,pin))
    # An earlier input with a different immutable policy cannot be moved into
    # the anchor's execution without explicit staff reconciliation.
    if len({pin['policy_version_id'] for _,_,pin in bindings})!=1:
        raise ProductionToolError('Resume inputs belong to different published policies.')
    batch={'job_id':resume_job_id,'epoch':epoch(conversation),'anchor_id':ids[-1],
           'inputs':[{'id':row.id,'sha256':input_hash(row),'provider_message_id':row.provider_message_id} for row in inputs]}
    return bindings,batch


def verify_resume_batch(db, scope, conversation, inbound, *, run=None):
    """Verify the immutable source set at preparation, dispatch and completion."""
    from app.modules.sales_agent.models import SalesFollowUpJob, SalesInboundJob, AgentRun
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    from app.modules.sales_agent.continuity import epoch, state
    from app.modules.sales_agent.engine_router import event_scope, PIN_KEY
    from .staged_runtime import _policy
    meta=inbound.metadata_json or {};batch=meta.get('hermes_resume_batch')
    if batch is None:
        if run is not None and (run.input_snapshot or {}).get('hermes_resume_batch') is not None:
            raise ProductionToolError('Resume batch binding disappeared.')
        return [inbound]
    if (not isinstance(batch,dict) or batch.get('anchor_id')!=inbound.id or batch.get('epoch')!=epoch(conversation)
            or state(conversation).get('last_inbound_message_id')!=inbound.id):
        raise ProductionToolError('Resume batch was superseded.')
    job=db.get(SalesFollowUpJob,batch.get('job_id'))
    if (not job or job.conversation_id!=scope.conversation_id or job.kind!='resume' or job.status!='processed'
            or (job.payload_json or {}).get('hermes_resume_batch')!=batch):
        raise ProductionToolError('Resume batch has no durable release receipt.')
    items=batch.get('inputs') or []
    if not 2<=len(items)<=MAX_INPUTS or len({x.get('id') for x in items})!=len(items) or items[-1].get('id')!=inbound.id:
        raise ProductionToolError('Invalid resume source list.')
    if run is not None and (run.input_snapshot or {}).get('hermes_resume_batch')!=batch:
        raise ProductionToolError('Reserved run has a different resume source list.')
    rows=[]; anchor_pin=meta.get(PIN_KEY) or {}
    for item in items:
        row=scoped_messages_query(db,conversation).filter_by(id=item['id'],channel=conversation.channel,direction='inbound',role='user').one_or_none()
        rmeta=(row.metadata_json or {}) if row else {}; pin=rmeta.get(PIN_KEY) or {}
        if (not row or row.provider_message_id!=item.get('provider_message_id') or input_hash(row)!=item.get('sha256')
                or row.status not in {'received','processed'} or rmeta.get('hermes_resume_batch')!=batch
                or rmeta.get('lead_id')!=scope.lead_id or rmeta.get('project_id')!=scope.project_id
                or not rmeta.get('continuity_recorded') or pin.get('engine')!='hermes'
                or pin.get('policy_version_id')!=anchor_pin.get('policy_version_id')
                or any(pin.get(k)!=v for k,v in event_scope(conversation,f'{conversation.provider}:{row.provider_message_id}').items())):
            raise ProductionToolError('Resume source changed or is outside the opportunity.')
        if row.id!=inbound.id:
            if not rmeta.get('awaiting_resume') or rmeta.get('handled_by_message_id') or db.query(AgentRun).filter_by(event_id=pin['event_id']).first():
                raise ProductionToolError('Earlier resume input was already handled or executed.')
            prior=db.query(SalesInboundJob).filter_by(conversation_id=conversation.id,message_id=row.id).one_or_none()
            if prior is not None and prior.status!='awaiting_resume':
                raise ProductionToolError('Earlier resume input was independently released.')
        rows.append(row)
    if [(r.created_at,r.id) for r in rows]!=sorted((r.created_at,r.id) for r in rows):
        raise ProductionToolError('Resume sources are out of chronological order.')
    return rows
