"""Structured production coordinator. No legacy graph or text-based asset selection."""
from .execution import now as workflow_now

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.core.config import settings
from app.modules.ai_core.models import AIConfiguration
from app.modules.onboarding_versions import require_capability
from app.modules.projects.models import Project, SalesAssetShare
from app.modules.projects import sales_asset_service, asset_share_service
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.governance.services import create_intervention_case, escalation_reason
from .models import AgentRun, SalesConversation, SalesFollowUpJob, SalesMessage
from .dialogue_store import Scope, load, save, check_scope, DialogueConflict
from .dialogue_models import SalesDialogueEvent
from .runtime_policy import RuntimePolicy
from .understanding_service import preview
from .understanding_contract import Understanding
from .dialogue_shadow import recorded_offers
from .dialogue_tasks import restricted
from .dialogue_orchestrator import run_turn
from .dialogue_composer import compose
from .commercial_context import build_commercial_context
from .conversation_scope import scoped_messages_query
from .turn_context import choice_index, latest_outbound
from .continuity_policy import explicit_opt_out, evidenced_pause_reason, dismissed_trigger, confirmed_controls
from .language_policy import LanguageHold

ENGINE='sales-active/1.0'


def authorize_part(db,conversation,lead,metadata):
    """Re-check each multipart send after any earlier provider call committed."""
    db.refresh(conversation);db.refresh(lead)
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,lead.id)
    check_scope(db,scope)
    if not selected_policy(db,scope):raise PermissionError('Active cohort was disabled.')
    if lead.deleted_at or (lead.is_opt_out and metadata.get('control_outcome')!='opt_out'):
        raise PermissionError('Lead no longer permits messages.')
    if conversation.is_paused and conversation.pause_reason!=metadata.get('expected_pause_reason'):
        raise PermissionError('Manual control interrupted dispatch.')
    from .execution import permitted
    if not permitted(lead) and metadata.get('control_outcome')!='opt_out':
        raise PermissionError('Messaging consent was withdrawn.')
    project=db.get(Project,scope.project_id)
    from .execution import simulated
    if project.profile and metadata.get('control_outcome') != 'opt_out' and not (simulated(scope) and project.is_demo):
        db.refresh(project.profile);require_capability(project.profile)
    if not metadata.get('control_outcome'):
        from .sales_policy import policy_context, compliance_action_holds
        from .commercial_context import confirmed_profile_facts
        holds=compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile)))
        newly_held=holds-set(metadata.get('policy_holds_at_prepare') or [])
        if newly_held & set(metadata.get('requested_topics') or []):
            raise PermissionError('Approved action restrictions changed before dispatch; review this response.')
    ids=metadata.get('sales_asset_share_ids') or []
    if ids:
        approved={a.id for a in sales_asset_service.approved_for_turn(db,project_id=scope.project_id,company_id=scope.company_id,channel=conversation.channel)}
        shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(ids),SalesAssetShare.company_id==scope.company_id,
            SalesAssetShare.project_id==scope.project_id,SalesAssetShare.lead_id==scope.lead_id).all()
        if len(shares)!=len(ids) or any(s.sales_asset_id not in approved or s.revoked or s.expires_at<=workflow_now(datetime) for s in shares):
            raise PermissionError('Material approval changed before dispatch.')
        if metadata.get('material_delivery_version'):
            from .material_delivery import validate_shares
            if not validate_shares(db,scope,shares,metadata,subset=True):
                raise PermissionError('The exact approved material changed before dispatch.')


def selected_policy(db,scope):
    from .turn_configuration import published_configuration
    try:
        agent, _ = published_configuration(db, scope.company_id)
    except ValueError:
        # Selection is unconditional, even before a model is configured. Control
        # events (especially STOP) never depend on a model/publication existing.
        # The interpreter validates configuration before any commercial action.
        return RuntimePolicy()
    return RuntimePolicy.model_validate(agent.get('runtime_config') or {})


def _current(db,scope,control=False):
    conversation=db.query(SalesConversation).filter_by(id=scope.conversation_id).populate_existing().with_for_update().one()
    check_scope(db,scope)
    lead=db.query(Lead).filter_by(id=scope.lead_id).populate_existing().one()
    if lead.deleted_at or lead.is_opt_out or (conversation.is_paused and not control):
        raise PermissionError('Manual control, opt-out or a changed opportunity interrupted this turn.')
    project=db.query(Project).filter_by(id=scope.project_id,company_id=scope.company_id).populate_existing().one()
    from .execution import simulated, permitted
    if (lead.is_demo or project.is_demo) and conversation.channel != 'simulation':
        raise PermissionError('Demo data may only use explicit simulation.')
    if conversation.channel == 'simulation' and not simulated(scope):
        raise PermissionError('Simulation adapter is required.')
    if project.profile and not control and not (simulated(scope) and project.is_demo):
        db.refresh(project.profile)
        require_capability(project.profile)
    if not permitted(lead) and not control:
        raise PermissionError('Messaging consent is not granted.')
    return conversation,lead,project


def _references(db,conversation,state,message):
    offers=recorded_offers(db,conversation)
    from .next_flow import selected
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    last=latest_outbound(db,conversation.id,skip_language_holds=selected(scope))
    meta=(last.metadata_json or {}) if last else {}
    # A plain answer supersedes old ordinals; explicit names can still resolve.
    state.offers=offers
    if meta.get('selected_property_type_id') and state.selected_property_type_id is None:
        from app.modules.projects.models import ProjectPropertyType
        identifier=meta['selected_property_type_id']
        if db.query(ProjectPropertyType).filter_by(id=identifier,project_id=conversation.project_id).first():
            state.selected_property_type_id=identifier
    return state,meta


def _confirmed_offer_understanding(u,meta,text):
    from .service import _affirmative_slot_reply
    # Exact assent has meaning only against the immediately preceding server
    # offer. It is not a generic material/appointment intent classifier.
    if _affirmative_slot_reply(text) and not u.requires_clarification:
        positive=[r for r in u.requests if r.polarity=='request' and r.topic.value!='other']
        if not positive and meta.get('material_offer'):
            payload=u.model_dump(mode='json')
            payload['requests']=[dict(id='confirmed_material',topic='materials',subject=None,polarity='request',evidence=text)]
            payload['all_of']=['confirmed_material'];payload['alternatives']=[]
            return Understanding.model_validate(payload)
        if not positive and meta.get('release_offer'):
            topic=meta['release_offer']['topic'];subject=meta['release_offer'].get('subject')
            payload=u.model_dump(mode='json')
            payload['requests']=[dict(id='confirmed_release',topic=topic,subject=subject,polarity='request',evidence=text)]
            payload['all_of']=['confirmed_release'];payload['alternatives']=[]
            # The explicit server question provides contextual evidence for yes.
            payload['releases']=[dict(topic=topic,subject=subject,evidence=text)]
            return Understanding.model_validate(payload)
    return u


def _materials(db,scope,conversation,lead,run,outcome,previous_meta):
    """Rehydrate approved IDs; diagnostic URLs are never sent to the lead."""
    tasks={t.id:t for t in outcome.state.tasks}
    approved={a.id:a for a in sales_asset_service.approved_for_turn(db,project_id=scope.project_id,
        company_id=scope.company_id,channel=conversation.channel)}
    fresh=build_commercial_context(db,project=db.get(Project,scope.project_id),company_id=scope.company_id,
        lead_id=scope.lead_id,channel=conversation.channel)
    metadata={a['asset_id']:a for a in fresh['available_assets']}
    from .service import _affirmative_slot_reply
    confirmed_ids=set((previous_meta.get('material_offer') or {}).get('asset_ids') or []) if _affirmative_slot_reply(
        scoped_messages_query(db,conversation).filter_by(id=run.input_snapshot['message_id']).one().content) else set()
    selection={}
    pending=[]
    unit_fallback=False
    for result in outcome.results:
        task=tasks.get(result.operation_id)
        if not task or task.topic.value!='materials' or task.status in {'cancelled','completed'} or restricted(outcome.state,task):
            continue
        if task.status=='awaiting_user' and not result.data.get('materials'):
            continue
        unit_fallback|=bool(result.data.get('requested_unit_id'))
        for material in result.data.get('materials',[]):
            aid=material['asset_id']
            if aid not in approved:
                continue
            if task.subject is None and confirmed_ids and aid not in confirmed_ids:
                continue
            direct=material.get('coverage')=='requested_tag'
            if not direct and aid not in confirmed_ids:
                pending.append(aid);continue
            selection.setdefault(aid,{'subjects':set(),'tasks':set()})
            selection[aid]['subjects'].add(task.subject)
            selection[aid]['tasks'].add(task.id)
    links,share_ids,delivered=[],[],set()
    for aid,choice in selection.items():
        asset=approved[aid];data=metadata[aid]
        if data.get('has_file'):
            url,share=asset_share_service.issue(db,company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id,
                source_id=asset.source_id,sales_asset_id=aid,channel=conversation.channel,agent_run_id=run.id)
            contents=', '.join(asset.content_tags or [asset.asset_type]).replace('_',' ')
            links.append(f"{asset.display_name} — contains {contents}: {url}")
            share_ids.append(share.id);delivered.update(choice['tasks'])
        for link in data.get('links',[]):
            if link['kind'] not in choice['subjects']:
                continue
            url,share=asset_share_service.issue(db,company_id=scope.company_id,project_id=scope.project_id,lead_id=scope.lead_id,
                source_id=asset.source_id,sales_asset_id=aid,channel=conversation.channel,agent_run_id=run.id,target_url=link['url'])
            links.append(f"{link.get('label') or link['kind']}: {url}");share_ids.append(share.id);delivered.update(choice['tasks'])
    offer={'asset_ids':list(dict.fromkeys(pending))} if pending else None
    if offer:
        names=', '.join(approved[aid].display_name for aid in offer['asset_ids'])
        question=f"I have {names}. It may contain useful related information, but the requested photo coverage is not confirmed. Would you like that file?"
        if unit_fallback:question=f"I have {names} for the property type. Coverage for the specific unit is not confirmed. Would you like those materials?"
    else:
        question=''
    # Pending files not selected by the user must not be silently completed.
    for tid in delivered:
        tasks[tid].status='awaiting_user'  # awaiting durable outbound receipt
    return links,share_ids,offer,question,delivered


def _appointment(db,scope,conversation,lead,project,outcome,inbound):
    from . import live_service as live
    from .service import _confirm_or_request_location
    u=outcome.state.last_understanding
    from .next_flow import selected as next_selected
    if next_selected(scope) and not u.appointment_query:
        from .reschedule_service import should_handle,handle as reschedule
        previous=latest_outbound(db,conversation.id,skip_language_holds=True)
        previous_meta=(previous.metadata_json or {}) if previous else {}
        if u.wait:
            from .wait_service import handle as handle_wait
            return handle_wait(db,scope,conversation,lead,outcome,inbound,previous_meta)
        from .cancellation_service import should_handle as should_cancel,handle as cancel
        if should_cancel(u,previous_meta):return cancel(db,scope,conversation,lead,outcome,inbound,previous_meta)
        if should_handle(u,outcome.state,previous_meta,outcome):return reschedule(db,scope,conversation,lead,project,outcome,inbound,previous_meta)
    if next_selected(scope) and u.appointment_query and u.permits('appointment'):
        if u.requires_clarification or u.confidence<.8:return 'Which appointment would you like to review?',{},[]
        from .sales_policy import policy_context,compliance_action_holds
        from .commercial_context import confirmed_profile_facts
        if 'appointment' in compliance_action_holds(policy_context(db,scope,confirmed_profile_facts(project.profile))):
            return 'The Sales team needs to verify this appointment information.',{},[]
        from .appointment_context import AppointmentReadTool,render
        plan=getattr(outcome,'plan',None)
        read=next((r.data['appointment_query'] for r in outcome.results if 'appointment_query' in r.data),None)
        if plan and read is None:return 'I could not verify that appointment information in this turn. Please tell me which date you want to review.',{},[]
        result=read if read is not None else AppointmentReadTool(db,scope).execute({'category':u.appointment_query})
        for task in outcome.state.tasks:
            if task.topic.value=='appointment' and task.source_message_id==inbound.id:task.status='completed'
        return render(result),{'appointment_query':result},[]
    if next_selected(scope):
        from .first_booking import handle
        return handle(db,scope,conversation,lead,project,outcome,inbound)
    if not u.permits('appointment'):
        return '',{},[]
    plan=getattr(outcome,'plan',None)
    if plan and not any(t.id in plan['write_candidates_require_backend_authorization'] for t in outcome.state.tasks if t.topic.value=='appointment' and t.source_message_id==inbound.id):
        return '',{},[]
    if any(t.topic.value=='appointment' and (restricted(outcome.state,t) or t.status=='awaiting_user') for t in outcome.state.tasks if t.source_message_id==inbound.id):
        return '',{},[]
    if u.requires_clarification or u.confidence < .8:
        return 'Do you want to explore properties, review materials, or arrange a visit?',{},[]
    if any(r.kind=='ambiguous' for r in u.references) and choice_index(inbound.content) is None:
        return 'Which appointment or property option do you mean?',{},[]
    resolved=[]
    from .dialogue_tasks import resolve_reference
    for reference in u.references:
        value=resolve_reference(db,scope,outcome.state,reference)
        if value:resolved.append(value)
    if choice_index(inbound.content) is not None and not any(v['kind'] in {'appointment','location'} for v in resolved):
        # A property number is not permission to start/confirm an appointment.
        return 'Does that option refer to a property or an appointment time?',{},[]
    if project.profile:require_capability(project.profile,'appointments')
    ready,question,resume=_confirm_or_request_location(project,lead,inbound.content)
    if not ready:
        from .service import locations_for_project
        locations=locations_for_project(project)
        return question,{'location_offer':{'pending':True,'option_ids':[x['address'] for x in locations]}},[]
    slot=next((v for v in resolved if v['kind']=='appointment'),None)
    if slot:
        starts=datetime.fromisoformat(slot['id'])
        if starts.tzinfo:starts=starts.astimezone(timezone.utc).replace(tzinfo=None)
        from app.modules.sales_crm.scheduling import create_agent_appointment
        try:
            visit_kwargs={}
            if next_selected(scope):
                # Bind to the original slot offer, never whichever property the
                # lead happened to ask about afterwards. Legacy offers stay unknown.
                offer=next((o for o in outcome.state.offers if o.kind=='appointment' and slot['id'] in o.option_ids),None)
                row=scoped_messages_query(db,conversation).filter_by(id=offer.message_id).first() if offer else None
                binding=((row.metadata_json or {}).get('appointment_offer') or {}) if row else {}
                visit_kwargs={'visit_property_type_id':binding.get('property_type_id'),'visit_unit_id':binding.get('unit_id'),'capture_visit_context':True}
                if binding.get('visit_location'):visit_kwargs['visit_location']=binding['visit_location']
            meeting,user=create_agent_appointment(db,lead=lead,starts_at=starts,duration_minutes=45,modality='showroom',defer_calendar=True,**visit_kwargs)
        except HTTPException as exc:
            if exc.status_code!=409:raise
        else:
            meeting.source='agent_sms_active'
            conversation.stage='appointment_confirmed';conversation.is_paused=True;conversation.pause_reason='Appointment confirmed'
            lead.pipeline_stage='S09_HANDOFF';lead.agent_status='appointment_confirmed';lead.next_action_at=None
            return live._appointment_confirmation(project=project,lead=lead,user=user,starts_at=meeting.meeting_time),{'meeting_id':meeting.id},[{'type':'appointment_confirmed','meeting_id':meeting.id}]
    reply,slots=live._availability_reply(db,project=project,inbound_text=resume or inbound.content,now=workflow_now(datetime))
    lead.pipeline_stage='S08_APPOINTMENT'
    offer={'slots':[s.isoformat() for s in slots],'duration_minutes':45,'project_timezone':project.timezone or 'UTC'}
    if next_selected(scope):offer.update(project_id=scope.project_id,property_type_id=outcome.state.selected_property_type_id,
        unit_id=outcome.state.selected_unit_id,visit_location=(lead.meta_form_data or {}).get('selected_visit_location'))
    return reply,{'appointment_offer':offer},[{'type':'request_available_slots'}]


def _calendar_after_commit(db,meeting_id,scope):
    """DB booking is already durable; deterministic event ID prevents duplicates."""
    if not meeting_id:return
    from .booking_models import SalesBookingOperation
    operation=db.query(SalesBookingOperation).filter_by(meeting_id=meeting_id,company_id=scope.company_id,lead_id=scope.lead_id).first()
    if operation:
        from .reschedule_models import SalesRescheduleOperation
        replacement=db.query(SalesRescheduleOperation).filter_by(replacement_meeting_id=meeting_id,company_id=scope.company_id,lead_id=scope.lead_id).first()
        if replacement:
            from .reschedule_service import advance_effect
            advance_effect(db,replacement.id)
            return
        from .first_booking import sync_calendar
        sync_calendar(db,operation.id)
        from .reschedule_service import advance_for_meeting
        advance_for_meeting(db,scope,meeting_id)
        return
    meeting=db.query(Meeting).filter_by(id=meeting_id,project_id=scope.project_id,lead_id=scope.lead_id).with_for_update().one()
    from app.modules.sales_crm.models import MeetingStatus
    if (meeting.calendar_sync_status not in {'pending','failed'} or meeting.is_demo
        or meeting.status!=MeetingStatus.CONFIRMED or meeting.meeting_time<=workflow_now(datetime)):return
    from app.modules.sales_crm.models import CalendarConnection
    connection=db.query(CalendarConnection).filter_by(user_id=meeting.assigned_sales_user_id,provider='google',status='connected').first()
    if not connection:return
    from app.modules.users.models import User
    user=db.get(User,meeting.assigned_sales_user_id)
    if not user or user.company_id!=scope.company_id:raise PermissionError('Foreign calendar owner.')
    from app.integrations.gcalendar_client import create_calendar_event_for_connection
    project=db.get(Project,scope.project_id);lead=db.get(Lead,scope.lead_id)
    try:
        event=create_calendar_event_for_connection(db,connection,title=f'{project.name} visit with {lead.full_name}',
            description='Appointment coordinated by Black Penguin.',location=meeting.visit_address or '',
            start_time=meeting.meeting_time,end_time=meeting.meeting_time+timedelta(minutes=meeting.duration_minutes),
            timezone_name=project.timezone or 'UTC',attendee_email=lead.email,event_id='bp'+meeting.id.replace('-',''))
        meeting.gcal_event_id=event['id'];meeting.meeting_url=event.get('htmlLink');meeting.calendar_sync_status='synced'
    except Exception:
        meeting.calendar_sync_status='failed'
    db.commit()


def retry_active_calendars(db,limit=10):
    """Bounded worker retry; no legacy bookings or disabled cohorts touched."""
    from .first_booking import retry_calendars
    retry_calendars(db,limit)
    from .reschedule_service import retry_effects
    retry_effects(db,limit)
    from .cancellation_service import retry_effects as retry_cancellations
    retry_cancellations(db,limit)
    from app.modules.sales_crm.models import MeetingStatus
    rows=db.query(Meeting).filter(Meeting.source=='agent_sms_active',Meeting.status==MeetingStatus.CONFIRMED,
        Meeting.calendar_sync_status.in_(['pending','failed']),Meeting.meeting_time>workflow_now(datetime)).order_by(
        Meeting.created_at).limit(limit).all()
    for meeting in rows:
        conversation=db.query(SalesConversation).filter_by(project_id=meeting.project_id,lead_id=meeting.lead_id).first()
        if not conversation:continue
        scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
        if selected_policy(db,scope):_calendar_after_commit(db,meeting.id,scope)


def active_followup_requires_review(db,conversation):
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    if not selected_policy(db,scope):return False
    from .next_flow import selected as next_selected
    if next_selected(scope):
        previous=latest_outbound(db,conversation.id)
        if previous and (previous.metadata_json or {}).get('language_hold'):
            return True  # Wait for the requested English input; do not resume a stale task.
    from .sales_policy import policy_context, custom_compliance
    from .commercial_context import confirmed_profile_facts
    project=db.get(Project,scope.project_id)
    return custom_compliance(policy_context(db,scope,confirmed_profile_facts(project.profile)))


def active_followup_result(db,scope):
    """A cadence event has no new user intent or permission to execute actions."""
    if isinstance(scope,SalesConversation):
        scope=Scope(scope.company_id,scope.project_id,scope.id,scope.lead_id)
    if not selected_policy(db,scope):return None
    conversation,lead,project=_current(db,scope)
    from .sales_policy import next_question
    context=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
    from .next_flow import selected as next_selected
    if next_selected(scope):
        from .lead_profile import qualification
        _,_,question=qualification(lead,context['confirmed_project_facts'])
    else:_,question=next_question(lead,context['confirmed_project_facts'])
    _,state=load(db,scope)
    chosen=next((p['property_type'] for p in context['property_types'] if p['id']==state.selected_property_type_id),None)
    reply=question or ('Would you like to continue reviewing '+chosen+'?' if chosen else 'Would you like to continue with property details, approved materials, or financing?')
    return {'proposed_reply':reply+' Reply STOP to opt out.',
        'model':'deterministic-active-followup','prompt_snapshot':{},'proposed_actions':[],
        'primary_intent':'scheduled_follow_up','requires_human':False,'policy_violations':[],
        'response_policy_trace':{'engine':ENGINE,'workflow_version':'sales-current/1.0','source':'cadence_no_new_user_intent'}}


async def maybe_process_active(db,conversation,inbound,*,event_id_override=None):
    from . import live_service as live
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    event_id=event_id_override or f'{conversation.provider}:{inbound.provider_message_id or inbound.id}'
    existing=db.query(AgentRun).filter_by(event_id=event_id).first()
    if existing and existing.conversation_id != conversation.id:
        raise DialogueConflict('The inbound event belongs to another conversation.')
    sticky=bool(existing and existing.graph_version==ENGINE)
    if existing and existing.graph_version != ENGINE and existing.status not in {'completed','blocked'}:
        # Historical effects may already exist. Never reinterpret or overwrite
        # an unfinished legacy event under a different workflow.
        existing.error_code='historical_turn_requires_reconciliation'
        existing.status='blocked';db.commit()
        return True
    policy=selected_policy(db,scope)
    if policy:
        from .first_booking import recover_booking_pause
        recover_booking_pause(db,conversation)
    if not policy:return sticky  # Never replay an unfinished new-engine turn through legacy.
    if not scoped_messages_query(db,conversation).filter_by(id=inbound.id,direction='inbound',role='user').first():
        raise PermissionError('Inbound message belongs to another opportunity.')
    if existing and existing.status in {'completed','blocked'}:return True
    lead=db.get(Lead,scope.lead_id)
    if not lead or (lead.is_opt_out and not (sticky and (existing.output_snapshot or {}).get('reply_ready'))):return True
    exact_stop=explicit_opt_out(inbound.content)
    if conversation.is_paused and not exact_stop and not (sticky and (existing.output_snapshot or {}).get('reply_ready')):
        return True
    run=existing if sticky else None
    if not (run and (run.output_snapshot or {}).get('reply_ready')):
        try:
            conversation,lead,project=_current(db,scope,control=exact_stop)
        except PermissionError:
            return True
        run=live._prepare_run(db,conversation=conversation,event_id=event_id,message_id=inbound.id)
        if run is None:return True
        run.graph_version=ENGINE;run.toolset_version='sales-actions/1.0'
        db.commit()
        try:
            from .next_flow import selected as next_selected
            next_enabled=next_selected(scope)
            from .moderation import precheck as moderation_precheck
            hard_moderation=moderation_precheck(inbound.content) if next_enabled and not exact_stop else None
            if next_enabled and not exact_stop and not hard_moderation and not evidenced_pause_reason(inbound.content):
                from .language_policy import detect,scoped_names,credential_request
                if not credential_request(inbound.content):
                    language_context=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
                    previous=latest_outbound(db,conversation.id,skip_language_holds=True)
                    previous_data=(previous.metadata_json or {}) if previous else {}
                    contextual=any(previous_data.get(k) for k in ('qualification_offer','material_offer','appointment_offer','control_confirmation','release_offer','property_catalog_offer'))
                    decision=detect(inbound.content,names=scoped_names(project,lead,language_context),contextual_answer=contextual)
                    if decision.needs_reentry:raise LanguageHold(decision)
            revision,state=load(db,scope)
            state,previous_meta=_references(db,conversation,state,inbound)
            # A bounded explicit assent can release a prohibition only when the
            # immediately preceding server message asked that precise question.
            release_offer=previous_meta.get('release_offer')
            if release_offer and live._affirmative_slot_reply(inbound.content):
                state.constraints=[c for c in state.constraints if not (c.topic.value==release_offer['topic'] and c.subject==release_offer.get('subject'))]
            revision,state=save(db,scope,event_key='active-context:'+inbound.id,expected_revision=revision,state=state,
                metadata={'engine':ENGINE,'workflow_version':'sales-current/1.0','message_id':inbound.id})
            protected=evidenced_pause_reason(inbound.content)
            if next_enabled and not protected:
                from .language_policy import credential_request
                if credential_request(inbound.content):protected='SECURITY'
            if previous_meta.get('control_confirmation')=='human' and live._affirmative_slot_reply(inbound.content):
                protected='HUMAN_REQUESTED'
            if hard_moderation:protected=hard_moderation['reason']
            if protected and not next_enabled and dismissed_trigger(lead,conversation.id,protected,inbound.content):
                protected=None
            from .sales_policy import policy_context, compliance_action_holds
            commercial=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
            approved_policy=policy_context(db,scope,commercial['confirmed_project_facts'])
            action_holds=compliance_action_holds(approved_policy)
            if protected or exact_stop:
                u=Understanding.model_validate(dict(version='sales-understanding/1.0',requests=[dict(id='protected',
                    topic='opt_out' if exact_stop else 'human',polarity='request',evidence=inbound.content[:2000])],
                    all_of=['protected'],alternatives=[],constraints=[],references=[],preferences=[],
                    requires_clarification=False,clarification_question=None,confidence=1.0))
                interpreted_revision=revision
            else:
                interpreted=await asyncio.wait_for(preview(db,scope,inbound_message_id=inbound.id,expected_revision=revision,
                    event_key='active-understanding:'+inbound.id,active=True),timeout=45)
                if interpreted.status!='accepted':
                    # Keep the rejected response and request evidence, not just
                    # a generic error snapshot, before composing a safe reply.
                    db.commit()
                    raise ValueError('Understanding could not be validated.')
                u=_confirmed_offer_understanding(interpreted.state.last_understanding,previous_meta,inbound.content)
                if next_enabled:
                    from .first_booking import enrich_understanding
                    u=enrich_understanding(u,previous_meta,inbound.content)
                    from .reschedule_service import enrich as enrich_reschedule
                    u=enrich_reschedule(u,previous_meta,inbound.content)
                    from .cancellation_service import enrich as enrich_cancellation
                    u=enrich_cancellation(u,previous_meta,inbound.content)
                    from .wait_service import enrich as enrich_wait
                    u=enrich_wait(u,previous_meta,inbound.content)
                u=confirmed_controls(u,inbound.content,pause_reason=protected)
                interpreted_revision=interpreted.revision
            moderation_decision=None
            if next_enabled and not exact_stop:
                from .moderation import assess
                moderation_decision=assess(db,scope,inbound,u,event_id)
                if moderation_decision and moderation_decision['disposition']=='pause':protected=moderation_decision['reason']
                if moderation_decision and moderation_decision['disposition'] in {'warn','boundary'}:
                    u=Understanding.model_validate({**u.model_dump(),'requests':[{'id':'moderation_boundary','topic':'other','subject':None,'polarity':'request','evidence':inbound.content[:2000]}],
                        'all_of':['moderation_boundary'],'alternatives':[],'references':[],'constraints':[],'releases':[],'preferences':[],
                        'visit':None,'reschedule':None,'cancellation':None,'wait':None,'courtesy':None,'selected_reference_id':None,'appointment_query':None,'requires_clarification':False,'clarification_question':None,'confidence':1.0})
            if u.confidence < .8 and not u.requires_clarification:
                u=u.model_copy(update={'requires_clarification':True,'clarification_question':'Could you clarify whether you want property details, materials, financing, or a visit?'})
            # Legal/commercial approvals hold the action, not the conversation.
            advisory=escalation_reason(inbound.content)
            if not protected and not exact_stop and advisory in {'LEGAL_QUESTION','COMPLEX_NEGOTIATION'}:
                u=u.model_copy(update={'requires_clarification':True,'clarification_question':'The Sales team needs to review that legal or commercial exception. I can continue helping with approved property information.'})
            outcome=run_turn(db,scope,message_id=inbound.id,understanding=u,expected_revision=interpreted_revision,
                event_key='active-runtime:'+inbound.id,max_steps=policy.max_steps,max_seconds=policy.max_seconds,
                **({'max_rounds':policy.max_rounds,'max_read_units':policy.max_read_units} if next_enabled else {}))
            if next_enabled:
                from .first_booking import apply_courtesy
                apply_courtesy(db,conversation,lead,outcome.state)
            conversation,lead,project=_current(db,scope,control=exact_stop)  # Manual takeover/consent/permissions win after inference.
            draft=compose(outcome,channel=conversation.channel,style=policy.composition_style)
            material_question=''
            reference_question=''
            reference_metadata={}
            appointment=''
            # Material discovery blocks are replaced by verified live links or
            # a specific fallback question; never send "not sent yet" diagnostics.
            text=draft.text
            text='\n\n'.join(b for b in text.split('\n\n') if not b.startswith('Available material:'))
            metadata={'engine':ENGINE,'workflow_version':'sales-current/1.0','inbound_message_id':inbound.id,'selected_property_type_id':outcome.state.selected_property_type_id}
            if next_enabled:metadata['selected_unit_id']=outcome.state.selected_unit_id
            if moderation_decision:metadata['moderation']=moderation_decision
            metadata['requested_topics']=sorted({r.topic.value for r in u.requests if r.polarity=='request'})
            metadata['policy_holds_at_prepare']=sorted(action_holds)
            if next_enabled:metadata['action_policy']=approved_policy.get('action_policy')
            if next_enabled:metadata['planning']=getattr(outcome,'plan',None)
            if u.requires_clarification and any(r.topic.value=='human' and r.polarity=='request' for r in u.requests):
                metadata['control_confirmation']='human'
            actions=[];share_ids=[];delivered=set();extra=[];links=[]
            safe_u=outcome.state.last_understanding
            if exact_stop:
                lead.is_opt_out=True;lead.consent_status='opted_out';lead.agent_status='paused';lead.next_action_at=None
                conversation.is_paused=True;conversation.pause_reason='Lead opted out'
                text='You have been unsubscribed and will not receive further messages.'
                metadata['control_outcome']='opt_out'
            elif protected:
                case=create_intervention_case(db,conversation=conversation,lead=lead,reason=protected,evidence=inbound.content)
                text="Your request and this conversation have been recorded for the Sales team to review."
                if next_enabled and protected=='SECURITY':
                    text="I cannot share private credentials or access another company's data. Your request has been recorded for the Sales team to review."
                if protected in {'THREAT','REPEATED_ABUSE'}:
                    text='This conversation needs the Sales team to review the '+('threatening message.' if protected=='THREAT' else 'continued personal abuse after the warning.')
                if moderation_decision and moderation_decision.get('id'):
                    from .moderation_models import SalesModerationIncident
                    db.get(SalesModerationIncident,moderation_decision['id']).intervention_case_id=case.id
                metadata.update(human_intervention_case_id=case.id,control_outcome='handoff',reason=protected,reason_source='verified_current_request')
            elif not safe_u.requires_clarification:
                for task in outcome.state.tasks:
                    if task.source_message_id==inbound.id and restricted(outcome.state,task) and safe_u.permits(task.topic,task.subject):
                        extra.append('You previously asked not to receive this. Do you want to allow it now?')
                        metadata['release_offer']={'topic':task.topic.value,'subject':task.subject}
                appointment,appointment_meta,actions=(None,{},[]) if 'appointment' in action_holds and not (safe_u.wait and safe_u.wait.action in {'cancel','decline'}) else _appointment(db,scope,conversation,lead,project,outcome,inbound)
                metadata.update(appointment_meta)
                if appointment:extra.append(appointment)
                if next_enabled and 'materials' not in action_holds:
                    from .material_delivery import deliver,VERSION as MATERIAL_VERSION
                    links,share_ids,offer,question,delivered,material_bindings=deliver(db,scope,conversation,lead,run,outcome,previous_meta)
                    metadata['material_delivery_version']=MATERIAL_VERSION
                    metadata['material_bindings']=material_bindings
                else:
                    links,share_ids,offer,question,delivered=([],[],{},None,set()) if 'materials' in action_holds else _materials(db,scope,conversation,lead,run,outcome,previous_meta)
                material_question=question or ''
                if offer:metadata['material_offer']=offer
                if question:extra.append(question)
                if any(t.topic.value in {'catalog','inventory','pricing'} and t.source_message_id==inbound.id and t.status=='completed' for t in outcome.state.tasks):
                    context=build_commercial_context(db,project=project,company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
                    selected=outcome.state.selected_property_type_id
                    broad=safe_u.permits('catalog')
                    metadata['property_catalog_offer']={'property_type_ids':[p['id'] for p in context['property_types'] if broad or not selected or p['id']==selected]}
                    extra.append('Which property option would you like to explore in more detail?')
            affected=sorted({t.topic.value for t in outcome.state.tasks if t.source_message_id==inbound.id} & action_holds)
            if (affected or advisory in {'LEGAL_QUESTION','COMPLEX_NEGOTIATION'}) and not conversation.is_paused:
                from .escalation_policy import notify_sales
                decision={'reason':advisory if advisory in {'LEGAL_QUESTION','COMPLEX_NEGOTIATION'} else 'ACTION_POLICY_REVIEW','disposition':'notify_sales','held_topics':affected,'conversation_paused':False}
                notify_sales(db,conversation=conversation,lead=lead,decision=decision,event_id=inbound.id,evidence=inbound.content)
                metadata['review_notice']=decision
                extra.append('The Sales team needs to verify that part of your request. I can continue helping with other approved information. What else would you like to know?')
            if next_enabled:
                from .wait_service import reconcile
                reconcile(db,scope,outcome.state,metadata)
            if conversation.is_paused:
                metadata['expected_pause_reason']=conversation.pause_reason
                db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id==conversation.id,SalesFollowUpJob.status.in_(['pending','processing'])).update({'status':'cancelled'},synchronize_session=False)
            if safe_u.requests and all(r.topic.value=='other' for r in safe_u.requests) and not safe_u.requires_clarification and not protected and not exact_stop:
                text='How can I help: property options, materials, pricing, financing, or delivery timing?'
            if (extra or links) and text=='I need clarification or verified information to answer this request.':
                text=''
            if next_enabled:
                from .planning_reply import continuation
                question,offer_metadata=continuation(outcome,action_holds)
                if question:extra.append(question)
                reference_question=question
                reference_metadata=offer_metadata
                metadata.update(offer_metadata)
            text='\n\n'.join(v for v in [text,*extra,*links] if v)
            if not text:text='Which property or approved material would you like to review?'
            if not conversation.is_paused and not lead.is_opt_out and not safe_u.requires_clarification:
                from .sales_policy import capture, next_question, missing_fields
                from app.modules.sales_crm.intelligence import update_lead_intelligence
                chosen=next((p for p in commercial['property_types'] if p['id']==outcome.state.selected_property_type_id),None)
                if next_enabled:
                    from .lead_profile import capture as capture_profile
                    plan=getattr(outcome,'plan',None) or {}
                    interest=plan.get('interest_reference')
                    refs=[r for i,r in enumerate(safe_u.references) if (r.id or 'legacy-'+str(i))==interest]
                    capture_u=safe_u.model_copy(update={'references':refs})
                    chosen_unit=next((v for v in commercial['inventory'] if v['id']==outcome.state.selected_unit_id and v.get('unit_code')),None)
                    capture_profile(db,scope,capture_u,inbound.id,
                        selected_property={**chosen,'unit_id':outcome.state.selected_unit_id} if interest and chosen else None,
                        selected_unit=chosen_unit if interest else None)
                else:capture(lead,safe_u,inbound.id,selected_property=chosen)
                history=scoped_messages_query(db,conversation).filter(SalesMessage.created_at<=inbound.created_at).order_by(SalesMessage.created_at,SalesMessage.id).all()
                lead_text,count=live._lead_intelligence_input(history)
                config=db.query(AIConfiguration).filter_by(company_id=None).first()
                if next_enabled:
                    # Reporting scores do not assign a persona or reinterpret
                    # workflow state from a bag of form/history keywords.
                    from app.modules.sales_crm.intelligence import calculate_score
                    from .lead_profile import qualification
                    calculate_score(db,lead,lead_text,count,scoring_config=(config.agent_ventas or {}).get('scoring_config',{}) if config else {})
                    metadata['qualification_missing']=qualification(lead,commercial['confirmed_project_facts'])[0]
                else:
                    update_lead_intelligence(db,lead,inbound_text=inbound.content,conversation_text=lead_text,message_count=count,
                        scoring_config=(config.agent_ventas or {}).get('scoring_config',{}) if config else {})
                    metadata['qualification_missing']=missing_fields(lead,commercial['confirmed_project_facts'])
                if not safe_u.requests and safe_u.preferences:
                    text='Thanks, I have recorded that information. What would you like to explore next?'
                if not next_enabled and safe_u.confidence>=.8 and not safe_u.permits('appointment') and not previous_meta.get('material_offer') and not links and not (
                    next_enabled and (getattr(outcome,'plan',{}).get('questions') or outcome.stop_reason in {'step_limit','time_limit','round_limit','read_cost_limit','capacity_limit'})):
                    if next_enabled:
                        _,field,question=qualification(lead,commercial['confirmed_project_facts'],record_asked=True)
                    else:field,question=next_question(lead,commercial['confirmed_project_facts'],record=True)
                    if question:
                        if not safe_u.requests and safe_u.preferences:
                            text='Thanks, I have recorded that information.'
                        text+='\n\n'+question
                        metadata['qualification_offer']={'field':field,'question':question}
            moderation_boundary=bool(moderation_decision and moderation_decision['disposition'] in {'warn','boundary'})
            if moderation_boundary:
                from .moderation import WARNING,BOUNDARY
                text=WARNING if moderation_decision['disposition']=='warn' else BOUNDARY
            if next_enabled and not exact_stop and not protected and not moderation_boundary:
                from .commercial_composer import compose as compose_commercial
                # Replace stacked catalog/material/qualification questions with
                # one continuation authorized against the current results.
                priority=reference_question or material_question
                priority_meta=reference_metadata if reference_question else {}
                if reference_question and metadata.get('material_offer'):
                    metadata.pop('material_offer',None)
                release=next((v for v in extra if v.startswith('You previously asked')),None)
                if release and not priority:priority=release
                if safe_u.requires_clarification:
                    from dataclasses import replace
                    draft=replace(draft,text=draft.text.replace(safe_u.clarification_question or '', '').strip())
                details=[]
                if priority and appointment and '?' in appointment:
                    # Keep a mixed request pending without putting two competing
                    # acceptance questions/offers into the same outbound message.
                    if metadata.get('cancellation_operation_id'):
                        from .cancellation_service import OPTIONAL_REASON
                        details.append(appointment.removesuffix(OPTIONAL_REASON))
                        metadata.pop('cancellation_followup',None)
                    elif metadata.get('booking_operation_id'):
                        closing=' What else would you like to know?' if metadata.get('reschedule_operation_id') else ' What else would you like to know before your visit?'
                        details.append(appointment.removesuffix(closing))
                        metadata.pop('post_booking_question',None)
                    else:
                        metadata.pop('appointment_offer',None)
                        metadata.pop('location_offer',None)
                        metadata.pop('booking_confirmation',None)
                        metadata.pop('reschedule_confirmation',None)
                        metadata.pop('reschedule_offer',None)
                        metadata.pop('reschedule_meeting_offer',None)
                        metadata.pop('cancellation_confirmation',None)
                        metadata.pop('cancellation_meeting_offer',None)
                        metadata.pop('wait_offer',None)
                        if metadata.pop('booking_property_question',None):metadata.pop('property_catalog_offer',None)
                        details.append('Your visit request remains pending while we review the information request.')
                elif appointment:details.append(appointment)
                if metadata.get('review_notice'):
                    details.append('The Sales team needs to verify the restricted part of your request. I can continue helping with other approved information.')
                details.extend(links)
                commercial_draft=await compose_commercial(db,scope,inbound=inbound,outcome=outcome,draft=draft,
                    commercial=commercial,lead=lead,metadata=metadata,previous_meta=previous_meta,
                    holds=action_holds,channel=conversation.channel,extra=details,
                    priority=priority,priority_meta=priority_meta)
                if conversation.is_paused and not (metadata.get('meeting_id') and conversation.pause_reason=='Appointment confirmed'):
                    raise PermissionError('Manual control interrupted composition.')
                conversation,lead,project=_current(db,scope,control=bool(metadata.get('meeting_id')))
                from .turn_configuration import digest
                from app.modules.projects.models import ProjectPropertyType,ProjectUnit
                for record_type in (ProjectPropertyType,ProjectUnit):
                    db.query(record_type).filter_by(project_id=scope.project_id).populate_existing().all()
                refreshed=build_commercial_context(db,project=project,company_id=scope.company_id,
                    lead_id=scope.lead_id,channel=conversation.channel)
                if digest(refreshed)!=digest(commercial):
                    raise ValueError('Approved commercial information changed during composition.')
                from .reschedule_service import validate_prepared
                validate_prepared(db,scope,metadata)
                from .cancellation_service import validate_prepared as validate_cancellation
                validate_cancellation(db,scope,metadata)
                from .wait_service import validate_saved
                validate_saved(db,scope,metadata)
                text=commercial_draft.text
                metadata['composition']=commercial_draft.trace
                metadata.update(commercial_draft.trace['closing_metadata'])
                if metadata.get('qualification_offer'):
                    from .lead_profile import qualification
                    qualification(lead,commercial['confirmed_project_facts'],record_asked=True)
            if draft.violations:
                text+='\n\nSome information could not be verified; no unsupported facts have been added.'
            if next_enabled:
                from .language_policy import detect,scoped_names
                decision=detect(text,names=scoped_names(project,lead,commercial),output=True)
                if decision.needs_reentry:raise LanguageHold(decision,output=True)
                metadata['language_policy']={'version':decision.version,'output_language':'en'}
            final_revision,state=save(db,scope,event_key='active-prepared:'+inbound.id,expected_revision=outcome.revision,state=outcome.state,
                metadata={'engine':ENGINE,'workflow_version':'sales-current/1.0','message_id':inbound.id,'draft':asdict(draft),'actions':actions,
                    'share_ids':share_ids,'delivery_state':'prepared_not_delivered'})
            interpretation=scope.query(db,SalesDialogueEvent).filter_by(event_key='active-understanding:'+inbound.id).first()
            trace=interpretation.payload_json['metadata'] if interpretation else {
                'model':'deterministic-control','prompt_snapshot':{},'prompt_configuration_id':None}
            run.model=trace['model'];run.prompt_snapshot=trace['prompt_snapshot'];run.prompt_configuration_id=trace['prompt_configuration_id']
            if next_enabled:
                metadata['configuration_ref']=trace.get('configuration_ref')
                metadata['playbook_selection']=trace.get('playbook_selection')
                metadata['turn_context_version']=trace.get('turn_context_version')
                metadata['turn_context_sha256']=trace.get('turn_context_sha256')
            run.input_snapshot={**run.input_snapshot,'understanding':safe_u.model_dump(mode='json'),'runtime_policy':policy.model_dump()}
            run.output_snapshot={'engine':ENGINE,'workflow_version':'sales-current/1.0','reply_ready':True,'reply':text,'metadata':metadata,'proposed_actions':actions,
                'sales_asset_share_ids':share_ids,'delivered_task_ids':list(delivered),'state_revision':final_revision,
                'requires_human':metadata.get('control_outcome')=='handoff','policy_violations':[]}
            run.status='prepared';conversation.updated_at=workflow_now(datetime);lead.last_interaction_at=workflow_now(datetime)
            db.add_all([run,conversation,lead]);db.commit()
        except LanguageHold as hold:
            # Input holds occur before reference/task changes. Output rejection
            # rolls back all proposed effects before any external dispatch.
            rejected_trace={}
            if hold.output:
                with db.no_autoflush:
                    event=scope.query(db,SalesDialogueEvent).filter_by(event_key='active-understanding:'+inbound.id).first()
                    trace=(event.payload_json.get('metadata') or {}) if event else {}
                    rejected_trace={key:trace.get(key) for key in ('model','configuration_ref','playbook_selection','model_request_sha256')}
            db.rollback()
            from .language_policy import REENTRY,OUTPUT_FALLBACK,VERSION
            run=db.query(AgentRun).filter_by(event_id=event_id).one()
            run.model='deterministic-language-policy';run.prompt_configuration_id=None
            run.prompt_snapshot={'version':VERSION,'decision':hold.decision.metadata()}
            run.error_code='reply_language_rejected' if hold.output else None
            run.output_snapshot={'engine':ENGINE,'workflow_version':'sales-current/1.0','reply_ready':True,'reply':OUTPUT_FALLBACK if hold.output else REENTRY,
                'metadata':{'engine':ENGINE,'workflow_version':'sales-current/1.0','inbound_message_id':inbound.id,'language_hold':True,
                            'output_rejected':hold.output,'language_policy':hold.decision.metadata(),
                            'rejected_turn':rejected_trace},
                'sales_asset_share_ids':[],'delivered_task_ids':[],'proposed_actions':[],
                'requires_human':False,'policy_violations':[]}
            run.status='prepared';db.commit()
        except DialogueConflict:
            raise
        except PermissionError:
            db.rollback();return True
        except Exception as exc:
            db.rollback()
            run=db.query(AgentRun).filter_by(event_id=event_id).one()
            interpretation=scope.query(db,SalesDialogueEvent).filter_by(event_key='active-understanding:'+inbound.id).first()
            trace=(interpretation.payload_json.get('metadata') or {}) if interpretation else {}
            if trace:
                run.model=trace.get('model') or run.model
                run.prompt_snapshot=trace.get('prompt_snapshot') or run.prompt_snapshot
                run.prompt_configuration_id=trace.get('prompt_configuration_id')
            run.error_code=trace.get('error_code') or type(exc).__name__
            from .runtime_errors import response as error_response
            reply, suppress, consecutive = error_response(db, conversation, run)
            run.output_snapshot={'engine':ENGINE,'workflow_version':'sales-current/1.0','reply_ready':True,'reply':reply,
                'suppress_duplicate_error_reply':suppress,'consecutive_processing_failures':consecutive,
                'metadata':{'engine':ENGINE,'workflow_version':'sales-current/1.0','inbound_message_id':inbound.id},'error_code':type(exc).__name__,
                'interpretation_outcome':trace.get('outcome'),'interpretation_attempt_count':len(trace.get('interpretation_attempts') or []),
                'sales_asset_share_ids':[],'delivered_task_ids':[],'policy_violations':[]}
            run.status='prepared';db.commit()
    # Durable effect receipts precede provider sends. Retry dispatch does not
    # repeat booking, handoff, interpretation or token issuance.
    data=dict(run.output_snapshot or {})
    conversation=db.query(SalesConversation).filter_by(id=scope.conversation_id).populate_existing().with_for_update().one()
    check_scope(db,scope)
    lead=db.query(Lead).filter_by(id=scope.lead_id).populate_existing().one()
    if data.get('suppress_duplicate_error_reply'):
        run.status='completed';run.completed_at=workflow_now(datetime);db.commit()
        return True
    metadata=dict(data.get('metadata') or {})
    expected_pause=metadata.get('expected_pause_reason')
    if metadata.get('meeting_id') and not metadata.get('booking_operation_id'):expected_pause='Appointment confirmed'
    own_control=bool(metadata.get('control_outcome') or metadata.get('meeting_id'))
    if metadata.get('control_outcome')=='handoff':
        from app.modules.governance.models import HumanInterventionCase
        case=db.get(HumanInterventionCase,metadata.get('human_intervention_case_id'))
        # Governance stores its protected human-readable pause reason.
        own_control=bool(case and case.status=='open' and lead.agent_status=='human_control')
    if conversation.is_paused and not (own_control and conversation.pause_reason==expected_pause):return True
    if lead.deleted_at or (lead.is_opt_out and metadata.get('control_outcome')!='opt_out'):return True
    from .execution import permitted
    if not permitted(lead) and metadata.get('control_outcome')!='opt_out':return True
    if not selected_policy(db,scope):return True
    project=db.query(Project).filter_by(id=scope.project_id,company_id=scope.company_id).populate_existing().one()
    from .execution import simulated
    if project.profile and metadata.get('control_outcome') != 'opt_out' and not (simulated(scope) and project.is_demo):
        db.refresh(project.profile)
        require_capability(project.profile)
    approved_ids={a.id for a in sales_asset_service.approved_for_turn(db,project_id=scope.project_id,company_id=scope.company_id,channel=conversation.channel)}
    shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(data.get('sales_asset_share_ids') or []),
        SalesAssetShare.company_id==scope.company_id,SalesAssetShare.project_id==scope.project_id,
        SalesAssetShare.lead_id==scope.lead_id,SalesAssetShare.agent_run_id==run.id).all()
    exact_valid=True
    if metadata.get('material_delivery_version'):
        from .material_delivery import validate_shares
        exact_valid=validate_shares(db,scope,shares,metadata)
    if not exact_valid or len(shares)!=len(data.get('sales_asset_share_ids') or []) or any(s.sales_asset_id not in approved_ids or s.revoked or s.expires_at<=workflow_now(datetime) for s in shares):
        if metadata.get('material_delivery_version'):
            data['reply']='\n\n'.join(v for v in data['reply'].split('\n\n') if '/projects/a/' not in v)
            data['reply']+='\n\nSome requested materials changed or are unavailable. No new file link has been sent.'
        else:
            data['reply']="Some requested materials are no longer approved to share. No new file link has been sent."
        data['sales_asset_share_ids']=[]
        data['delivered_task_ids']=[]
    metadata['sales_asset_share_ids']=data.get('sales_asset_share_ids') or []
    _calendar_after_commit(db,metadata.get('meeting_id'),scope)
    if metadata.get('cancellation_operation_id'):
        from .cancellation_service import advance_effect
        advance_effect(db,metadata['cancellation_operation_id'])
    # Retain the original intent result even if dispatch-time approval changed.
    run.output_snapshot={**run.output_snapshot,'reply':data['reply']}
    dispatched=await live._dispatch(db,conversation=conversation,lead=lead,content=data['reply'],role='assistant',agent_run_id=run.id,
        metadata=metadata,idempotency_key='active-reply:'+run.id)
    parts=(run.output_snapshot or {}).get('delivery_parts') or [{'status':dispatched.status}]
    if any(p['status'] not in {'sent','delivered','queued','accepted','sending','scheduled'} for p in parts):
        raise RuntimeError('Provider did not accept the active response.')
    if dispatched.status in {'queued','sending','scheduled','accepted'} and not dispatched.provider_message_id:
        raise RuntimeError('Provider acceptance is unknown; keep the durable turn pending.')
    revision,state=load(db,scope)
    replaced={tid for row in metadata.get('material_bindings',[]) if row['share_id'] in metadata.get('sales_asset_share_ids',[]) for tid in row.get('replaces_task_ids',[])}
    for task in state.tasks:
        if task.id in replaced:
            task.status='cancelled';task.blocked_reason='accepted_related_alternative'
        if task.id in data.get('delivered_task_ids',[]):task.status='completed'
        if task.source_message_id==inbound.id and task.topic.value in {'human','opt_out'} and own_control:task.status='completed'
        if task.source_message_id==inbound.id and task.topic.value=='appointment' and metadata.get('meeting_id'):task.status='completed'
    from .next_flow import selected as next_selected
    if next_selected(scope) and not metadata.get('language_hold') and run.input_snapshot.get('understanding'):
        from .turn_memory import remember
        remember(state,message_id=inbound.id,at=inbound.created_at,
            understanding=Understanding.model_validate(run.input_snapshot['understanding']),
            answered_topics=[t.topic for t in state.tasks if t.status=='completed' and t.source_message_id==inbound.id],
            interest={'property_type_id':metadata.get('selected_property_type_id'),'unit_id':metadata.get('selected_unit_id')})
    if not scope.query(db,SalesDialogueEvent).filter_by(event_key='active-receipt:'+inbound.id).first():
        save(db,scope,event_key='active-receipt:'+inbound.id,expected_revision=revision,state=state,
            metadata={'engine':ENGINE,'workflow_version':'sales-current/1.0','message_id':inbound.id,'run_id':run.id,'delivery_state':'provider_accepted_not_delivery_confirmed','share_ids':metadata['sales_asset_share_ids']})
    if next_selected(scope):
        from .moderation import accepted_warning
        accepted_warning(db,conversation,metadata)
    run.status='completed';run.completed_at=workflow_now(datetime);db.commit()
    from .first_booking import cadence_stopped
    if not conversation.is_paused and not lead.is_opt_out and not run.error_code and not metadata.get('language_hold') and not cadence_stopped(db,conversation):
        live._schedule_next_action(db,conversation,lead,event_id,refresh_pending=True);db.commit()
    elif run.error_code:
        jobs=db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').all()
        for job in jobs:
            if job.reason.endswith('_cadence'):job.status='cancelled'
        lead.next_action_at=min((job.scheduled_at for job in jobs if job.status=='pending'),default=None)
        db.commit()
    return True
