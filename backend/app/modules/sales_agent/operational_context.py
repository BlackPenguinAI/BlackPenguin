"""Allowlisted operational facts for Agent, Schedule and the audited staff Monitor."""
from datetime import datetime,timezone
from fastapi import HTTPException
from .dialogue_store import Scope,load,check_scope
from .models import SalesConversation,SalesMessage,AgentRun
from .conversation_scope import scoped_messages_query
from .appointment_context import AppointmentReadTool
from .booking_models import SalesBookingOperation
from .reschedule_models import SalesRescheduleOperation
from .cancellation_models import SalesCancellationOperation
from .wait_models import SalesWaitRequest
from .moderation_models import SalesModerationIncident
from app.modules.projects.models import Project,ProjectPropertyType,ProjectUnit
from app.modules.sales_crm.models import Lead,Meeting
from app.modules.users.models import UserRole
from app.modules.users.project_access import project_ids_for_user,require_project_access


def scoped_conversation(db,actor,identifier):
    row=db.query(SalesConversation).filter_by(id=identifier,company_id=actor.company_id).first()
    if not row:raise HTTPException(404,'Conversation not found.')
    require_project_access(db,actor,row.project_id)
    lead=db.get(Lead,row.lead_id)
    if actor.role==UserRole.SALES and lead.assigned_sales_user_id!=actor.id:raise HTTPException(404,'Conversation not found.')
    return row


def safe_message(message):
    from .monitor import redact
    import re
    links=[]
    def preserve(match):links.append(match.group());return 'SCOPEDMATERIALLINK'+str(len(links)-1)+'END'
    content=re.sub(r'https?://[^\s?]+/(?:api/v1/)?projects/a/[A-Za-z0-9_-]+',preserve,message.content)
    content=redact(content)
    for index,value in enumerate(links):content=content.replace('SCOPEDMATERIALLINK'+str(index)+'END',value)
    def public_metadata(value):
        if isinstance(value,dict):return {k:'[REDACTED]' if k in {'prompt_snapshot','system_prompt','published_guidance','raw_response'} else public_metadata(v) for k,v in value.items()}
        if isinstance(value,list):return [public_metadata(v) for v in value]
        return value
    return {c.name:(redact(public_metadata(message.metadata_json)) if c.name=='metadata_json' else content if c.name=='content' else getattr(message,c.name)) for c in message.__table__.columns}


def snapshot(db,conversation,*,allowed_projects=None,scope_limited=False,meeting_only_id=None):
    from .monitor import redact
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id);check_scope(db,scope)
    allowed=set(allowed_projects) if allowed_projects is not None else {p.id for p in db.query(Project).filter_by(company_id=scope.company_id).all()}
    lead=db.get(Lead,scope.lead_id);project=db.get(Project,scope.project_id)
    revision,state=load(db,scope)
    product=db.query(ProjectPropertyType).filter_by(id=state.selected_property_type_id,project_id=scope.project_id).first() if state.selected_property_type_id else None
    unit=db.query(ProjectUnit).filter_by(id=state.selected_unit_id,project_id=scope.project_id).first() if state.selected_unit_id else None
    visits=AppointmentReadTool(db,scope).execute({'category':'all','limit':30})['appointments']
    visits=[v for v in visits if v['project_id'] in allowed and (not meeting_only_id or v['id']==meeting_only_id)]
    for visit in visits:
        meeting=db.get(Meeting,visit['id']);visit['calendar_status']=meeting.calendar_sync_status
    def rows(model):return db.query(model).filter_by(company_id=scope.company_id,lead_id=scope.lead_id).order_by(model.created_at.desc()).limit(40).all()
    effects=[]
    for row in rows(SalesBookingOperation):
        if row.project_id not in allowed:continue
        effects.append({'id':row.id,'kind':'booking','meeting_id':row.meeting_id,'status':row.calendar_status,'attempts':row.calendar_attempts,'last_error':row.last_error,'next_attempt_at':row.next_attempt_at})
    for row in rows(SalesRescheduleOperation):
        destination=(row.snapshot_json.get('replacement') or {}).get('context',{}).get('project_id')
        if row.project_id not in allowed or destination not in allowed:continue
        effects.append({'id':row.id,'kind':'replacement_calendar','meeting_id':row.replacement_meeting_id,'status':row.calendar_status,'attempts':row.attempts,'last_error':row.last_error,'next_attempt_at':row.next_attempt_at})
    for row in rows(SalesCancellationOperation):
        if row.project_id not in allowed or row.booking_project_id not in allowed:continue
        effects.append({'id':row.id,'kind':'cancellation_calendar','meeting_id':row.meeting_id,'status':row.calendar_status,'attempts':row.attempts,'last_error':row.last_error,'next_attempt_at':row.next_attempt_at})
        effects.append({'id':row.id,'kind':'cancellation_notification','meeting_id':row.meeting_id,'status':row.notification_status,'attempts':row.notification_attempts,'last_error':row.notification_last_error,'next_attempt_at':row.notification_next_attempt_at})
    if meeting_only_id:effects=[e for e in effects if e['meeting_id']==meeting_only_id]
    waits=[]
    for row in rows(SalesWaitRequest):
        if row.project_id not in allowed or row.target_project_id not in allowed:continue
        saved=row.snapshot_json;context=saved['context'];prefs=saved['preferences']
        waits.append({'id':row.id,'status':row.status,'close_reason':row.close_reason,'project_name':context.get('project_name'),'property':context.get('property_type_name'),'unit':context.get('unit_code'),
            'date_from':prefs.get('date_from'),'date_until':prefs.get('date_until'),'timezone':prefs.get('timezone'),'channel':row.channel,
            'expires_at':row.expires_at,'next_check_at':row.next_check_at,'last_error':row.last_error,'attempts':row.attempts,'notified_message_id':row.notified_message_id})
    proposals=[]
    for kind,value in [('booking',state.booking_proposal),('replacement',state.reschedule_proposal),('cancellation',state.cancellation_proposal)]:
        if not value:continue
        context=value.get('context') or value.get('target_context') or value.get('appointment') or {}
        if context.get('project_id') not in allowed:continue
        proposals.append({'kind':kind,'id':value.get('id'),'project_name':context.get('project_name'),'property':context.get('property_type_name'),'unit':context.get('unit_code'),
            'starts_at':(value.get('option') or {}).get('starts_at') or context.get('starts_at'),'specialist':(value.get('option') or {}).get('specialist_name') or context.get('specialist_name'),
            'expires_at':value.get('expires_at'),'status':'expired' if value.get('expires_at') and datetime.fromisoformat(value['expires_at']).astimezone(timezone.utc)<=datetime.now(timezone.utc) else 'awaiting_exact_confirmation'})
    cases=[];moderation=[]
    if not scope_limited:
        from .conversation_review import review_snapshot
        cases=review_snapshot(db,conversation)['intervention_cases']
        moderation=[{'id':r.id,'category':r.category,'disposition':r.disposition,'evidence':r.evidence,'created_at':r.created_at,'warning_accepted_at':r.warning_accepted_at,'intervention_case_id':r.intervention_case_id,'dismissed_at':r.dismissed_at}
            for r in db.query(SalesModerationIncident).filter_by(company_id=scope.company_id,project_id=scope.project_id,conversation_id=scope.conversation_id,lead_id=scope.lead_id).order_by(SalesModerationIncident.created_at.desc()).limit(20).all()]
    run=db.query(AgentRun).filter_by(conversation_id=scope.conversation_id).order_by(AgentRun.started_at.desc(),AgentRun.id.desc()).first()
    if run and not scoped_messages_query(db,conversation).filter_by(id=(run.input_snapshot or {}).get('message_id')).first():run=None
    meta=((run.output_snapshot or {}).get('metadata') or {}) if run else {}
    latest=scoped_messages_query(db,conversation).filter_by(direction='outbound').order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    from .active_service import selected_policy
    from .next_flow import selected
    from app.modules.onboarding_versions import require_capability
    from .models import SalesInboundJob
    ready=True
    try:
        if project.profile:require_capability(project.profile)
    except Exception:ready=False
    inbound=scoped_messages_query(db,conversation).filter_by(direction='inbound',role='user').filter(SalesMessage.metadata_json['resume_context'].as_boolean().isnot(True)).order_by(SalesMessage.created_at.desc(),SalesMessage.id.desc()).first()
    job=db.query(SalesInboundJob).filter_by(message_id=inbound.id).order_by(SalesInboundJob.created_at.desc()).first() if inbound else None
    configuration_ready = True
    from .continuity import snapshot as continuity_snapshot
    continuity=continuity_snapshot(db,conversation) if not scope_limited else None
    from app.modules.sales_crm.models import LeadObjection
    objections=[] if scope_limited else [{'kind':o.objection_type,'evidence':o.evidence[:500],'status':o.status}
        for o in db.query(LeadObjection).filter_by(lead_id=lead.id,status='open').order_by(LeadObjection.updated_at.desc()).limit(5).all()]
    response_run=db.get(AgentRun,(latest.metadata_json or {}).get('agent_run_id')) if latest else None
    if response_run and response_run.conversation_id!=conversation.id:response_run=None
    try:
        if not scope_limited:
            from .turn_configuration import published_configuration
            published_configuration(db, scope.company_id)
    except (ValueError, TypeError):
        configuration_ready = False
    return redact({'execution':{} if scope_limited else {'workflow_version':'sales-current/1.0',
            'configuration_ready':configuration_ready,'new_engine_selected':True,'new_flow_enabled':True,
            'project_ready':ready,'job_status':job.status if job else None,'job_error':job.error_code if job else None,'job_next_attempt_at':job.scheduled_at if job else None},
        'version':'sales-operational-context/1.0','scope_limited':scope_limited,'revision':revision if not scope_limited else None,
        'chat':{'status':'scope_limited' if scope_limited else 'unsubscribed' if lead.is_opt_out or lead.consent_status!='granted' else 'paused' if conversation.is_paused else 'open',
            'pause_reason':conversation.pause_reason if not scope_limited else None,'cadence':None if scope_limited else state.cadence_status,'cadence_reason':None if scope_limited else state.cadence_stop_reason,
            'can_resume':not scope_limited and not lead.is_opt_out and lead.consent_status=='granted' and conversation.is_paused},
        'current_interest':None if scope_limited else {'project_name':project.name,'property':product.name if product else None,'unit':unit.unit_code if unit else None,'source':'current enquiry; does not change a booked visit'},
        'appointments':visits,'proposals':proposals if not scope_limited else [],'waits':waits if not scope_limited else [],'effects':effects,
        'tasks':[] if scope_limited else [{'id':t.id,'topic':t.topic,'status':t.status,'blocked_reason':t.blocked_reason} for t in state.tasks[-25:]],
        'interventions':cases,'moderation':moderation,'continuity':continuity,
        'handoff_summary':None if scope_limited else {'stage':lead.pipeline_stage,'intent_tier':lead.intent_tier,
            'qualification_summary':lead.qualification_summary,'segment':lead.assigned_segment,'objections':objections,
            'next_step':'Review and answer the pending lead messages' if continuity['pending_message_count'] else 'Wait for the lead to reply',
            'pending_topics':sorted({t.topic.value for t in state.tasks if t.status in {'pending','awaiting_user','blocked','suspended'}}),
            'last_lead_message':inbound.content[:500] if inbound and not (inbound.metadata_json or {}).get('resume_context') else None,
            'pending_messages':continuity['pending_message_count']},
        'trace':{} if scope_limited else {'workflow_version':meta.get('workflow_version'),'prompt_version':(run.prompt_snapshot or {}).get('version') if run else None,'engine':run.graph_version if run else None,'model':run.model if run else None,'run_status':run.status if run else None,'error_code':run.error_code if run else None,
            'configuration':meta.get('configuration_ref'),'language_validation':meta.get('language_policy'),'action_policy':meta.get('action_policy'),
            'last_message_status':latest.status if latest else None,'last_message_at':latest.created_at if latest else None,
            'last_response_engine':response_run.graph_version if response_run else None,'last_response_model':response_run.model if response_run else None,
            'last_response_role':latest.role if latest else None,
            'receipt_semantics':'provider accepted is distinct from device delivery'},
        'bounded':{'appointments':30,'operations_per_kind':40,'moderation':20,'tasks':25}})


def meeting_context(db,actor,meeting_id):
    meeting=db.query(Meeting).join(Project,Project.id==Meeting.project_id).filter(Meeting.id==meeting_id,Project.company_id==actor.company_id).first()
    if not meeting:raise HTTPException(404,'Visit not found.')
    require_project_access(db,actor,meeting.project_id)
    if actor.role==UserRole.SALES and meeting.assigned_sales_user_id!=actor.id:raise HTTPException(404,'Visit not found.')
    allowed=project_ids_for_user(db,actor)
    receipt=db.query(SalesBookingOperation).filter_by(company_id=actor.company_id,meeting_id=meeting.id).first()
    conversation=db.get(SalesConversation,receipt.conversation_id) if receipt else db.query(SalesConversation).filter_by(company_id=actor.company_id,lead_id=meeting.lead_id).order_by(SalesConversation.created_at.desc()).first()
    if not conversation: return {'version':'sales-operational-context/1.0','scope_limited':True,'appointments':[],'effects':[],'chat':{'status':'no_agent_context'},'trace':{}}
    lead=db.get(Lead,meeting.lead_id)
    limited=conversation.project_id not in allowed or actor.role==UserRole.SALES and lead.assigned_sales_user_id!=actor.id
    return snapshot(db,conversation,allowed_projects=allowed,scope_limited=limited,meeting_only_id=meeting.id if limited else None)


def retry_effect(db,actor,conversation,kind,identifier,note):
    from app.modules.users.models import TENANT_MANAGER_ROLES
    from app.modules.governance.services import record_platform_event
    if actor.role not in TENANT_MANAGER_ROLES:raise HTTPException(403,'Only Company managers can retry synchronization.')
    models={'booking':SalesBookingOperation,'replacement':SalesRescheduleOperation,'cancellation':SalesCancellationOperation}
    if kind not in models or len((note or '').strip())<3:raise HTTPException(422,'Select an operation and explain the retry.')
    query=db.query(models[kind]).filter_by(id=identifier,company_id=conversation.company_id,lead_id=conversation.lead_id).populate_existing()
    row=query.first() if kind=='cancellation' else query.with_for_update().first()
    if not row:raise HTTPException(404,'Operation not found.')
    projects={row.project_id,conversation.project_id}
    if kind=='replacement':projects.add(row.snapshot_json['replacement']['context']['project_id'])
    if kind=='cancellation':projects.update([row.booking_project_id,*[t['project_id'] for t in row.snapshot_json['cleanup']]])
    for pid in projects:require_project_access(db,actor,pid)
    if kind=='cancellation':
        from .cancellation_service import reset_effects
        reset_effects(db,row,commit=False)
    else:
        if row.calendar_status in {'synced','completed','simulation','cancelled'}:raise HTTPException(409,'This synchronization is already complete or no longer eligible.')
        if kind=='booking' and db.query(SalesRescheduleOperation).filter_by(replacement_booking_operation_id=row.id).first():raise HTTPException(409,'Retry the replacement operation that owns this booking effect.')
        meeting=db.get(Meeting,row.meeting_id if kind=='booking' else row.replacement_meeting_id)
        if not meeting or meeting.status.value not in {'confirmed','scheduled'} or meeting.meeting_time<=datetime.utcnow():raise HTTPException(409,'The reservation is no longer eligible.')
        row.calendar_status='pending';row.last_error=None;row.next_attempt_at=datetime.utcnow()
        if kind=='booking':row.calendar_attempts=0
        else:
            row.attempts=0
            child=db.get(SalesBookingOperation,row.replacement_booking_operation_id)
            if child.calendar_status=='review':child.calendar_status='pending';child.calendar_attempts=0;child.last_error=None;child.next_attempt_at=datetime.utcnow()
    record_platform_event(db,actor=actor,company_id=conversation.company_id,event_type='sales_effect_retry',entity_type='sales_conversation',entity_id=conversation.id,
        reason=note.strip(),payload={'kind':kind,'operation_id':identifier,'lead_id':conversation.lead_id})
    db.commit();return {'status':'queued_for_recheck','operation_id':identifier,'kind':kind}
