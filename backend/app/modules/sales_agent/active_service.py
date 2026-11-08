"""Structured production coordinator. No legacy graph or text-based asset selection."""
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
    if lead.consent_status!='granted' and metadata.get('control_outcome')!='opt_out':
        raise PermissionError('Messaging consent was withdrawn.')
    project=db.get(Project,scope.project_id)
    if project.profile and metadata.get('control_outcome') != 'opt_out':
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
        if len(shares)!=len(ids) or any(s.sales_asset_id not in approved or s.revoked or s.expires_at<=datetime.utcnow() for s in shares):
            raise PermissionError('Material approval changed before dispatch.')


def selected_policy(db,scope):
    if not settings.SALES_DIALOGUE_RUNTIME_ENABLED:
        return None
    config=db.query(AIConfiguration).filter_by(company_id=None).first()
    policy=RuntimePolicy.model_validate((config.agent_ventas or {}).get('runtime_config') or {}) if config else RuntimePolicy()
    return policy if policy.mode=='active' and policy.selects(scope) else None


def _current(db,scope,control=False):
    conversation=db.query(SalesConversation).filter_by(id=scope.conversation_id).populate_existing().with_for_update().one()
    check_scope(db,scope)
    lead=db.query(Lead).filter_by(id=scope.lead_id).populate_existing().one()
    if lead.deleted_at or lead.is_opt_out or (conversation.is_paused and not control):
        raise PermissionError('Manual control, opt-out or a changed opportunity interrupted this turn.')
    project=db.query(Project).filter_by(id=scope.project_id,company_id=scope.company_id).populate_existing().one()
    if project.profile and not control:
        db.refresh(project.profile)
        require_capability(project.profile)
    if lead.consent_status!='granted' and not control:
        raise PermissionError('Messaging consent is not granted.')
    return conversation,lead,project


def _references(db,conversation,state,message):
    offers=recorded_offers(db,conversation)
    last=latest_outbound(db,conversation.id)
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
    for result in outcome.results:
        task=tasks.get(result.operation_id)
        if not task or task.topic.value!='materials' or task.status in {'cancelled','completed'} or restricted(outcome.state,task):
            continue
        if task.status=='awaiting_user' and not result.data.get('materials'):
            continue
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
    if not u.permits('appointment'):
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
            meeting,user=create_agent_appointment(db,lead=lead,starts_at=starts,duration_minutes=45,modality='showroom',defer_calendar=True)
        except HTTPException as exc:
            if exc.status_code!=409:raise
        else:
            meeting.source='agent_sms_active'
            conversation.stage='appointment_confirmed';conversation.is_paused=True;conversation.pause_reason='Appointment confirmed'
            lead.pipeline_stage='S09_HANDOFF';lead.agent_status='appointment_confirmed';lead.next_action_at=None
            return live._appointment_confirmation(project=project,lead=lead,user=user,starts_at=meeting.meeting_time),{'meeting_id':meeting.id},[{'type':'appointment_confirmed','meeting_id':meeting.id}]
    reply,slots=live._availability_reply(db,project=project,inbound_text=resume or inbound.content,now=datetime.utcnow())
    lead.pipeline_stage='S08_APPOINTMENT'
    return reply,{'appointment_offer':{'slots':[s.isoformat() for s in slots],'duration_minutes':45,'project_timezone':project.timezone or 'UTC'}},[{'type':'request_available_slots'}]


def _calendar_after_commit(db,meeting_id,scope):
    """DB booking is already durable; deterministic event ID prevents duplicates."""
    if not meeting_id:return
    meeting=db.query(Meeting).filter_by(id=meeting_id,project_id=scope.project_id,lead_id=scope.lead_id).with_for_update().one()
    from app.modules.sales_crm.models import MeetingStatus
    if (meeting.calendar_sync_status not in {'pending','failed'} or meeting.is_demo
        or meeting.status!=MeetingStatus.CONFIRMED or meeting.meeting_time<=datetime.utcnow()):return
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
    if not settings.SALES_DIALOGUE_RUNTIME_ENABLED:return
    from app.modules.sales_crm.models import MeetingStatus
    rows=db.query(Meeting).filter(Meeting.source=='agent_sms_active',Meeting.status==MeetingStatus.CONFIRMED,
        Meeting.calendar_sync_status.in_(['pending','failed']),Meeting.meeting_time>datetime.utcnow()).order_by(
        Meeting.created_at).limit(limit).all()
    for meeting in rows:
        conversation=db.query(SalesConversation).filter_by(project_id=meeting.project_id,lead_id=meeting.lead_id).first()
        if not conversation:continue
        scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
        if selected_policy(db,scope):_calendar_after_commit(db,meeting.id,scope)


def active_followup_requires_review(db,conversation):
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    if not selected_policy(db,scope):return False
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
    _,question=next_question(lead,context['confirmed_project_facts'])
    _,state=load(db,scope)
    chosen=next((p['property_type'] for p in context['property_types'] if p['id']==state.selected_property_type_id),None)
    reply=question or ('Would you like to continue reviewing '+chosen+'?' if chosen else 'Would you like to continue with property details, approved materials, or financing?')
    return {'proposed_reply':reply+' Reply STOP to opt out.',
        'model':'deterministic-active-followup','prompt_snapshot':{},'proposed_actions':[],
        'primary_intent':'scheduled_follow_up','requires_human':False,'policy_violations':[],
        'response_policy_trace':{'engine':ENGINE,'source':'cadence_no_new_user_intent'}}


async def maybe_process_active(db,conversation,inbound):
    from . import live_service as live
    scope=Scope(conversation.company_id,conversation.project_id,conversation.id,conversation.lead_id)
    event_id=f'{conversation.provider}:{inbound.provider_message_id or inbound.id}'
    existing=db.query(AgentRun).filter_by(event_id=event_id).first()
    sticky=bool(existing and existing.graph_version==ENGINE)
    policy=selected_policy(db,scope)
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
            revision,state=load(db,scope)
            state,previous_meta=_references(db,conversation,state,inbound)
            # A bounded explicit assent can release a prohibition only when the
            # immediately preceding server message asked that precise question.
            release_offer=previous_meta.get('release_offer')
            if release_offer and live._affirmative_slot_reply(inbound.content):
                state.constraints=[c for c in state.constraints if not (c.topic.value==release_offer['topic'] and c.subject==release_offer.get('subject'))]
            revision,state=save(db,scope,event_key='active-context:'+inbound.id,expected_revision=revision,state=state,
                metadata={'engine':ENGINE,'message_id':inbound.id})
            protected=evidenced_pause_reason(inbound.content)
            if previous_meta.get('control_confirmation')=='human' and live._affirmative_slot_reply(inbound.content):
                protected='HUMAN_REQUESTED'
            if protected and dismissed_trigger(lead,conversation.id,protected,inbound.content):
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
                u=confirmed_controls(u,inbound.content,pause_reason=protected)
                interpreted_revision=interpreted.revision
            if u.confidence < .8 and not u.requires_clarification:
                u=u.model_copy(update={'requires_clarification':True,'clarification_question':'Could you clarify whether you want property details, materials, financing, or a visit?'})
            # Legal/commercial approvals hold the action, not the conversation.
            advisory=escalation_reason(inbound.content)
            if not protected and not exact_stop and advisory in {'LEGAL_QUESTION','COMPLEX_NEGOTIATION'}:
                u=u.model_copy(update={'requires_clarification':True,'clarification_question':'The Sales team needs to review that legal or commercial exception. I can continue helping with approved property information.'})
            outcome=run_turn(db,scope,message_id=inbound.id,understanding=u,expected_revision=interpreted_revision,
                event_key='active-runtime:'+inbound.id,max_steps=policy.max_steps,max_seconds=policy.max_seconds)
            conversation,lead,project=_current(db,scope,control=exact_stop)  # Manual takeover/consent/permissions win after inference.
            draft=compose(outcome,channel=conversation.channel,style=policy.composition_style)
            # Material discovery blocks are replaced by verified live links or
            # a specific fallback question; never send "not sent yet" diagnostics.
            text=draft.text
            text='\n\n'.join(b for b in text.split('\n\n') if not b.startswith('Available material:'))
            metadata={'engine':ENGINE,'inbound_message_id':inbound.id,'selected_property_type_id':outcome.state.selected_property_type_id}
            metadata['requested_topics']=sorted({r.topic.value for r in u.requests if r.polarity=='request'})
            metadata['policy_holds_at_prepare']=sorted(action_holds)
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
                metadata.update(human_intervention_case_id=case.id,control_outcome='handoff',reason=protected,reason_source='verified_current_request')
            elif not safe_u.requires_clarification:
                for task in outcome.state.tasks:
                    if task.source_message_id==inbound.id and restricted(outcome.state,task) and safe_u.permits(task.topic,task.subject):
                        extra.append('You previously asked not to receive this. Do you want to allow it now?')
                        metadata['release_offer']={'topic':task.topic.value,'subject':task.subject}
                appointment,appointment_meta,actions=(None,{},[]) if 'appointment' in action_holds else _appointment(db,scope,conversation,lead,project,outcome,inbound)
                metadata.update(appointment_meta)
                if appointment:extra.append(appointment)
                links,share_ids,offer,question,delivered=([],[],{},None,set()) if 'materials' in action_holds else _materials(db,scope,conversation,lead,run,outcome,previous_meta)
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
            if conversation.is_paused:
                metadata['expected_pause_reason']=conversation.pause_reason
                db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id==conversation.id,SalesFollowUpJob.status.in_(['pending','processing'])).update({'status':'cancelled'},synchronize_session=False)
            if safe_u.requests and all(r.topic.value=='other' for r in safe_u.requests) and not safe_u.requires_clarification:
                text='How can I help: property options, materials, pricing, financing, or delivery timing?'
            if (extra or links) and text=='I need clarification or verified information to answer this request.':
                text=''
            text='\n\n'.join(v for v in [text,*extra,*links] if v)
            if not text:text='Which property or approved material would you like to review?'
            if not conversation.is_paused and not lead.is_opt_out and not safe_u.requires_clarification:
                from .sales_policy import capture, next_question, missing_fields
                from app.modules.sales_crm.intelligence import update_lead_intelligence
                chosen=next((p for p in commercial['property_types'] if p['id']==outcome.state.selected_property_type_id),None)
                capture(lead,safe_u,inbound.id,selected_property=chosen)
                history=scoped_messages_query(db,conversation).filter(SalesMessage.created_at<=inbound.created_at).order_by(SalesMessage.created_at,SalesMessage.id).all()
                lead_text,count=live._lead_intelligence_input(history)
                config=db.query(AIConfiguration).filter_by(company_id=None).first()
                update_lead_intelligence(db,lead,inbound_text=inbound.content,conversation_text=lead_text,message_count=count,
                                         scoring_config=(config.agent_ventas or {}).get('scoring_config',{}) if config else {})
                metadata['qualification_missing']=missing_fields(lead,commercial['confirmed_project_facts'])
                if not safe_u.requests and safe_u.preferences:
                    text='Thanks, I have recorded that information. What would you like to explore next?'
                if safe_u.confidence>=.8 and not safe_u.permits('appointment') and not previous_meta.get('material_offer') and not links:
                    field,question=next_question(lead,commercial['confirmed_project_facts'],record=True)
                    if question:
                        if not safe_u.requests and safe_u.preferences:
                            text='Thanks, I have recorded that information.'
                        text+='\n\n'+question
                        metadata['qualification_offer']={'field':field,'question':question}
            if draft.violations:
                text+='\n\nSome information could not be verified; no unsupported facts have been added.'
            final_revision,state=save(db,scope,event_key='active-prepared:'+inbound.id,expected_revision=outcome.revision,state=outcome.state,
                metadata={'engine':ENGINE,'message_id':inbound.id,'draft':asdict(draft),'actions':actions,
                    'share_ids':share_ids,'delivery_state':'prepared_not_delivered'})
            interpretation=scope.query(db,SalesDialogueEvent).filter_by(event_key='active-understanding:'+inbound.id).first()
            trace=interpretation.payload_json['metadata'] if interpretation else {
                'model':'deterministic-control','prompt_snapshot':{},'prompt_configuration_id':None}
            run.model=trace['model'];run.prompt_snapshot=trace['prompt_snapshot'];run.prompt_configuration_id=trace['prompt_configuration_id']
            run.input_snapshot={**run.input_snapshot,'understanding':safe_u.model_dump(mode='json'),'runtime_policy':policy.model_dump()}
            run.output_snapshot={'engine':ENGINE,'reply_ready':True,'reply':text,'metadata':metadata,'proposed_actions':actions,
                'sales_asset_share_ids':share_ids,'delivered_task_ids':list(delivered),'state_revision':final_revision,
                'requires_human':metadata.get('control_outcome')=='handoff','policy_violations':[]}
            run.status='prepared';conversation.updated_at=datetime.utcnow();lead.last_interaction_at=datetime.utcnow()
            db.add_all([run,conversation,lead]);db.commit()
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
            run.output_snapshot={'engine':ENGINE,'reply_ready':True,'reply':"I'm having trouble processing your message right now. You can ask about available properties, prices, or a visit, or request help from the Sales team.",
                'metadata':{'engine':ENGINE,'inbound_message_id':inbound.id},'error_code':type(exc).__name__,
                'interpretation_outcome':trace.get('outcome'),'interpretation_attempt_count':len(trace.get('interpretation_attempts') or []),
                'sales_asset_share_ids':[],'delivered_task_ids':[],'policy_violations':[]}
            run.status='prepared';db.commit()
    # Durable effect receipts precede provider sends. Retry dispatch does not
    # repeat booking, handoff, interpretation or token issuance.
    data=dict(run.output_snapshot or {})
    conversation=db.query(SalesConversation).filter_by(id=scope.conversation_id).populate_existing().with_for_update().one()
    check_scope(db,scope)
    lead=db.query(Lead).filter_by(id=scope.lead_id).populate_existing().one()
    metadata=dict(data.get('metadata') or {})
    expected_pause=metadata.get('expected_pause_reason')
    if metadata.get('meeting_id'):expected_pause='Appointment confirmed'
    own_control=bool(metadata.get('control_outcome') or metadata.get('meeting_id'))
    if metadata.get('control_outcome')=='handoff':
        from app.modules.governance.models import HumanInterventionCase
        case=db.get(HumanInterventionCase,metadata.get('human_intervention_case_id'))
        # Governance stores its protected human-readable pause reason.
        own_control=bool(case and case.status=='open' and lead.agent_status=='human_control')
    if conversation.is_paused and not (own_control and conversation.pause_reason==expected_pause):return True
    if lead.deleted_at or (lead.is_opt_out and metadata.get('control_outcome')!='opt_out'):return True
    if lead.consent_status!='granted' and metadata.get('control_outcome')!='opt_out':return True
    if not selected_policy(db,scope):return True
    project=db.query(Project).filter_by(id=scope.project_id,company_id=scope.company_id).populate_existing().one()
    if project.profile and metadata.get('control_outcome') != 'opt_out':
        db.refresh(project.profile)
        require_capability(project.profile)
    approved_ids={a.id for a in sales_asset_service.approved_for_turn(db,project_id=scope.project_id,company_id=scope.company_id,channel=conversation.channel)}
    shares=db.query(SalesAssetShare).filter(SalesAssetShare.id.in_(data.get('sales_asset_share_ids') or []),
        SalesAssetShare.company_id==scope.company_id,SalesAssetShare.project_id==scope.project_id,
        SalesAssetShare.lead_id==scope.lead_id,SalesAssetShare.agent_run_id==run.id).all()
    if len(shares)!=len(data.get('sales_asset_share_ids') or []) or any(s.sales_asset_id not in approved_ids or s.revoked or s.expires_at<=datetime.utcnow() for s in shares):
        data['reply']="Some requested materials are no longer approved to share. No new file link has been sent."
        data['sales_asset_share_ids']=[]
        data['delivered_task_ids']=[]
    metadata['sales_asset_share_ids']=data.get('sales_asset_share_ids') or []
    _calendar_after_commit(db,metadata.get('meeting_id'),scope)
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
    for task in state.tasks:
        if task.id in data.get('delivered_task_ids',[]):task.status='completed'
        if task.source_message_id==inbound.id and task.topic.value in {'human','opt_out'} and own_control:task.status='completed'
        if task.source_message_id==inbound.id and task.topic.value=='appointment' and metadata.get('meeting_id'):task.status='completed'
    if not scope.query(db,SalesDialogueEvent).filter_by(event_key='active-receipt:'+inbound.id).first():
        save(db,scope,event_key='active-receipt:'+inbound.id,expected_revision=revision,state=state,
            metadata={'engine':ENGINE,'message_id':inbound.id,'run_id':run.id,'delivery_state':'provider_accepted_not_delivery_confirmed','share_ids':metadata['sales_asset_share_ids']})
    run.status='completed';run.completed_at=datetime.utcnow();db.commit()
    if not conversation.is_paused and not lead.is_opt_out and not run.error_code:
        live._schedule_next_action(db,conversation,lead,event_id,refresh_pending=True);db.commit()
    elif run.error_code:
        jobs=db.query(SalesFollowUpJob).filter_by(conversation_id=conversation.id,status='pending').all()
        for job in jobs:
            if job.reason.endswith('_cadence'):job.status='cancelled'
        lead.next_action_at=min((job.scheduled_at for job in jobs if job.status=='pending'),default=None)
        db.commit()
    return True
