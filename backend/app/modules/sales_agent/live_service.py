"""Production SMS workflow sharing the same LangGraph and CRM services as simulation."""

from __future__ import annotations

from datetime import datetime, timedelta
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.postgres import SessionLocal
from app.integrations.twilio_client import send_sms
from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.intelligence import update_lead_intelligence
from app.modules.sales_crm.models import FunnelStage, Lead, LeadContact
from app.modules.sales_crm.calendar_links import calendar_invite_url, google_calendar_add_url
from app.modules.system_settings.services import get_twilio_config

from .graph import GRAPH_VERSION, TOOLSET_VERSION, build_sales_graph
from .models import AgentRun, OutboundMessage, SalesConversation, SalesFollowUpJob, SalesMessage
from .service import (
    _action_types, _appointment_confirmation, _availability_reply,
    _is_availability_request, _offered_slot_selection, _project_zone,
)
from app.modules.sales_crm.scheduling import create_agent_appointment, next_cadence_time


def normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return f"+{digits}"


def ensure_contact(db: Session, lead: Lead) -> LeadContact:
    phone = normalize_phone(lead.phone)
    contact = db.query(LeadContact).filter(
        LeadContact.company_id == lead.company_id,
        LeadContact.canonical_phone == phone,
    ).first()
    if not contact:
        contact = LeadContact(
            company_id=lead.company_id, canonical_phone=phone,
            full_name=lead.full_name, email=lead.email,
            preferred_channel="sms",
        )
        db.add(contact); db.flush()
    normalized_db_phone = Lead.phone
    for character in ("+", " ", "-", "(", ")"):
        normalized_db_phone = func.replace(normalized_db_phone, character, "")
    prior_leads = db.query(Lead).filter(
        Lead.company_id == lead.company_id,
        Lead.id != lead.id,
        normalized_db_phone == phone.removeprefix("+"),
    ).order_by(Lead.created_at.desc()).limit(20).all()
    matching = prior_leads
    contact.full_name = lead.full_name or contact.full_name
    contact.email = lead.email or contact.email
    contact.previous_projects = [
        {
            "lead_id": item.id, "project_id": item.project_id,
            "segment": item.assigned_segment, "intent_tier": item.intent_tier,
            "qualification_summary": item.qualification_summary,
            "last_interaction_at": item.last_interaction_at.isoformat() if item.last_interaction_at else None,
        }
        for item in matching
    ]
    lead.contact_id = contact.id
    db.add_all([contact, lead])
    return contact


def get_or_create_live_conversation(db: Session, lead: Lead) -> tuple[SalesConversation, bool]:
    config = get_twilio_config(db)
    thread_key = f"twilio:{normalize_phone(config.from_phone_number or '')}:{normalize_phone(lead.phone)}"
    existing = db.query(SalesConversation).filter(
        SalesConversation.provider_thread_key == thread_key,
    ).first()
    if existing:
        if existing.lead_id != lead.id and not existing.is_paused:
            raise HTTPException(status_code=409, detail="This phone already has an active SMS conversation on the shared sender.")
        if existing.lead_id != lead.id:
            existing.lead_id = lead.id
            existing.project_id = lead.project_id
            existing.campaign_id = lead.campaign_id
            existing.stage = "new"
            existing.is_paused = False
            existing.pause_reason = None
            existing.updated_at = datetime.utcnow()
            db.add(existing); db.flush()
            return existing, True
        return existing, False
    conversation = SalesConversation(
        company_id=lead.company_id, project_id=lead.project_id, campaign_id=lead.campaign_id,
        lead_id=lead.id, channel="sms", provider_thread_key=thread_key,
        automation_level=2, is_paused=False,
    )
    db.add(conversation); db.flush()
    return conversation, True


def resolve_inbound_conversation(db: Session, *, to_number: str, from_number: str) -> SalesConversation | None:
    key = f"twilio:{normalize_phone(to_number)}:{normalize_phone(from_number)}"
    return db.query(SalesConversation).filter(SalesConversation.provider_thread_key == key).first()


def _initial_message(lead: Lead, project: Project, campaign: ProjectCampaign | None) -> str:
    first_name = (lead.full_name or "there").split()[0]
    source = campaign.name if campaign else project.name
    return (
        f"Hi {first_name}, thanks for your interest in {source}. I'm Black Penguin's AI Sales Agent for "
        f"{project.name}. I can answer questions, help you compare the available options and coordinate a visit. "
        "What would be most useful to know first? Reply STOP to opt out."
    )


async def _dispatch(
    db: Session, *, conversation: SalesConversation, lead: Lead, content: str,
    role: str, agent_run_id: str | None, author_user_id: str | None = None,
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> SalesMessage:
    outbound = OutboundMessage(
        conversation_id=conversation.id, agent_run_id=agent_run_id,
        idempotency_key=idempotency_key or f"twilio:{conversation.id}:{uuid.uuid4()}", channel="sms",
        recipient=lead.phone, content=content, status="queued",
        approved_by_user_id=author_user_id,
        approved_at=datetime.utcnow() if author_user_id else None,
    )
    message = SalesMessage(
        conversation_id=conversation.id, channel="sms", direction="outbound", role=role,
        author_user_id=author_user_id, content=content, status="queued",
        metadata_json=metadata or {}, created_at=datetime.utcnow(),
    )
    db.add_all([outbound, message]); db.commit()
    try:
        result = await send_sms(db, to=lead.phone, body=content)
    except Exception as exc:
        outbound.status = "failed"; outbound.last_error = type(exc).__name__
        message.status = "failed"
        db.commit()
        raise
    sid = result.get("sid")
    status = result.get("status") or "queued"
    outbound.provider_message_id = sid; outbound.status = status; outbound.sent_at = datetime.utcnow()
    message.provider_message_id = sid; message.status = status
    db.commit(); db.refresh(message)
    return message


def _schedule_next_action(db: Session, conversation: SalesConversation, lead: Lead, event_id: str) -> None:
    if lead.is_opt_out or conversation.is_paused:
        return
    delays = {"hot": 24, "warm": 72, "cold": 24 * 14}
    hours = delays.get(lead.intent_tier, 72)
    project = db.query(Project).filter(Project.id == conversation.project_id).first()
    scheduled_at = next_cadence_time(
        now=datetime.utcnow(), timezone_name=project.timezone if project else "UTC", delay_hours=hours,
    )
    if not db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == conversation.id,
        SalesFollowUpJob.status == "pending",
    ).first():
        db.add(SalesFollowUpJob(
            conversation_id=conversation.id,
            idempotency_key=f"live-followup:{conversation.id}:{event_id}",
            scheduled_at=scheduled_at, reason=f"{lead.intent_tier}_cadence", attempt_number=1,
        ))
        lead.next_action_at = scheduled_at


async def start_live_lead(lead_id: str) -> None:
    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_demo.is_(False)).first()
        if not lead or not lead.project_id or lead.is_opt_out:
            return
        config = get_twilio_config(db)
        if not config.live_sms_enabled or config.verification_status != "verified":
            lead.agent_status = "waiting_for_twilio"
            db.commit(); return
        project = db.query(Project).filter(Project.id == lead.project_id, Project.company_id == lead.company_id).one()
        campaign = db.query(ProjectCampaign).filter(ProjectCampaign.id == lead.campaign_id).first() if lead.campaign_id else None
        ensure_contact(db, lead)
        try:
            conversation, is_new_lead_thread = get_or_create_live_conversation(db, lead)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            lead.agent_status = "duplicate_active_contact"
            db.commit()
            return
        if not is_new_lead_thread and db.query(SalesMessage).filter(SalesMessage.conversation_id == conversation.id).count():
            return
        content = _initial_message(lead, project, campaign)
        await _dispatch(db, conversation=conversation, lead=lead, content=content, role="assistant", agent_run_id=None, metadata={"event_kind": "meta_lead_first_contact"})
        lead.agent_status = "active"; lead.funnel_stage = FunnelStage.CONTACTED
        lead.pipeline_stage = "S01_RESEARCH"; lead.last_interaction_at = datetime.utcnow()
        _schedule_next_action(db, conversation, lead, f"initial:{lead.id}")
        db.commit()
    finally:
        db.close()


async def process_live_inbound(conversation_id: str, inbound_message_id: str) -> None:
    db = SessionLocal()
    try:
        conversation = db.query(SalesConversation).filter(SalesConversation.id == conversation_id).with_for_update().first()
        inbound = db.query(SalesMessage).filter(SalesMessage.id == inbound_message_id).first()
        if not conversation or not inbound or conversation.is_paused:
            return
        lead = db.query(Lead).filter(Lead.id == conversation.lead_id, Lead.company_id == conversation.company_id).one()
        project = db.query(Project).filter(Project.id == conversation.project_id, Project.company_id == conversation.company_id).one()
        if lead.is_opt_out:
            return
        if inbound.content.strip().upper() in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
            lead.is_opt_out = True; lead.consent_status = "opted_out"; lead.agent_status = "paused"
            conversation.is_paused = True; conversation.pause_reason = "Lead opted out"
            db.query(SalesFollowUpJob).filter(SalesFollowUpJob.conversation_id == conversation.id, SalesFollowUpJob.status == "pending").update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
            db.commit()
            await _dispatch(db, conversation=conversation, lead=lead, content="You have been unsubscribed and will not receive further messages.", role="assistant", agent_run_id=None, metadata={"event_kind": "opt_out"})
            return
        event_id = f"twilio:{inbound.provider_message_id or inbound.id}"
        run = AgentRun(
            conversation_id=conversation.id, event_id=event_id, mode="live", status="running",
            graph_version=GRAPH_VERSION, toolset_version=TOOLSET_VERSION,
            prompt_snapshot={}, model="pending", input_snapshot={"message_id": inbound.id},
        )
        db.add(run); db.commit(); db.refresh(run)
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id, "mode": "live", "conversation_id": conversation.id,
            "company_id": lead.company_id, "project_id": project.id, "campaign_id": lead.campaign_id,
            "lead_id": lead.id, "channel": "sms", "inbound_text": inbound.content,
            "event_kind": "lead_message", "requires_human": False, "policy_violations": [],
        })
        reply = result.get("proposed_reply")
        actions = result.get("proposed_actions", [])
        offered_slots = []
        selected = _offered_slot_selection(db, conversation_id=conversation.id, inbound_text=inbound.content, project=project, now=datetime.utcnow())
        if selected:
            try:
                meeting, user = create_agent_appointment(db, lead=lead, starts_at=selected, duration_minutes=45, modality="showroom")
                reply = _appointment_confirmation(project=project, lead=lead, user=user, starts_at=meeting.meeting_time)
                reply += (
                    f" Add to Google Calendar: {google_calendar_add_url(project=project, lead=lead, starts_at=meeting.meeting_time)}. "
                    f"Other calendar apps: {calendar_invite_url(meeting.id)}"
                )
                conversation.stage = "appointment_confirmed"; conversation.is_paused = True; conversation.pause_reason = "Appointment confirmed"
                lead.pipeline_stage = "S09_HANDOFF"; lead.agent_status = "appointment_confirmed"; lead.next_action_at = None
                actions = [{"type": "appointment_confirmed", "meeting_id": meeting.id}]
            except HTTPException as exc:
                if exc.status_code != 409: raise
                reply, offered_slots = _availability_reply(db, project=project, inbound_text=inbound.content, now=datetime.utcnow())
        elif _is_availability_request(inbound.content, now=datetime.utcnow(), zone=_project_zone(project)) or "request_available_slots" in _action_types(actions):
            reply, offered_slots = _availability_reply(db, project=project, inbound_text=inbound.content, now=datetime.utcnow())
        history = db.query(SalesMessage).filter(SalesMessage.conversation_id == conversation.id).order_by(SalesMessage.created_at).all()
        update_lead_intelligence(db, lead, inbound_text=inbound.content, conversation_text=" ".join(item.content for item in history[-20:]), message_count=len(history))
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {"reply": reply, "proposed_actions": actions, "requires_human": result.get("requires_human", False)}
        run.status = "completed"; run.completed_at = datetime.utcnow()
        conversation.updated_at = datetime.utcnow(); lead.last_interaction_at = datetime.utcnow()
        db.add_all([run, conversation, lead]); db.commit()
        # The LLM call runs without holding a database lock. Re-lock immediately
        # before dispatch so an administrator taking manual control wins the race.
        db.expire(conversation)
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == conversation.id,
        ).populate_existing().with_for_update().one()
        if reply and (
            not conversation.is_paused or conversation.pause_reason == "Appointment confirmed"
        ):
            await _dispatch(db, conversation=conversation, lead=lead, content=reply, role="assistant", agent_run_id=run.id, metadata={"appointment_offer": {"slots": [slot.isoformat() for slot in offered_slots], "duration_minutes": 45, "project_timezone": project.timezone or "UTC"}} if offered_slots else {})
        _schedule_next_action(db, conversation, lead, event_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def send_manual_message(db: Session, *, conversation_id: str, company_id: str, user_id: str, content: str) -> SalesMessage:
    conversation = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    ).with_for_update().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.channel != "sms":
        raise HTTPException(status_code=409, detail="Manual provider messages are available for live SMS conversations only.")
    if not conversation.is_paused:
        raise HTTPException(status_code=409, detail="Pause the AI before sending a manual SMS.")
    lead = db.query(Lead).filter(Lead.id == conversation.lead_id, Lead.company_id == company_id).one()
    if lead.is_opt_out:
        raise HTTPException(status_code=409, detail="This lead opted out of messaging.")
    message = await _dispatch(
        db, conversation=conversation, lead=lead, content=content,
        role="human", agent_run_id=None, author_user_id=user_id,
        metadata={"event_kind": "manual_sms"},
    )
    conversation.pause_reason = "Manual control active"
    conversation.updated_at = datetime.utcnow(); db.commit()
    return message


async def process_live_followup_job(job_id: str) -> None:
    """Generate one durable cadence message; safe to retry without duplicate SMS."""
    db = SessionLocal()
    try:
        job = db.query(SalesFollowUpJob).filter(SalesFollowUpJob.id == job_id).first()
        if not job or job.status != "processing":
            return
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == job.conversation_id,
        ).with_for_update().one()
        lead = db.query(Lead).filter(
            Lead.id == conversation.lead_id,
            Lead.company_id == conversation.company_id,
        ).one()
        if conversation.channel != "sms" or conversation.is_paused or lead.is_opt_out:
            job.status = "cancelled"; job.processed_at = datetime.utcnow(); db.commit(); return
        dispatch_key = f"twilio-followup:{job.id}"
        if db.query(OutboundMessage).filter(OutboundMessage.idempotency_key == dispatch_key).first():
            job.status = "processed"; job.processed_at = datetime.utcnow(); db.commit(); return
        project = db.query(Project).filter(
            Project.id == conversation.project_id,
            Project.company_id == conversation.company_id,
        ).one()
        event_id = f"followup:{job.id}"
        run = AgentRun(
            conversation_id=conversation.id, event_id=event_id, mode="live", status="running",
            graph_version=GRAPH_VERSION, toolset_version=TOOLSET_VERSION,
            prompt_snapshot={}, model="pending", input_snapshot={"follow_up_job_id": job.id},
        )
        db.add(run); db.commit(); db.refresh(run)
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id, "mode": "live", "conversation_id": conversation.id,
            "company_id": lead.company_id, "project_id": project.id,
            "campaign_id": lead.campaign_id, "lead_id": lead.id, "channel": "sms",
            "inbound_text": (
                "Write the next concise, helpful SMS follow-up based only on the verified context and chat. "
                "Do not invent urgency, inventory, price or availability. Include a simple question and opt-out language."
            ),
            "event_kind": "scheduled_follow_up", "requires_human": False, "policy_violations": [],
        })
        reply = result.get("proposed_reply")
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {"reply": reply, "proposed_actions": result.get("proposed_actions", [])}
        run.status = "completed" if reply and not result.get("requires_human") else "failed"
        run.error_code = result.get("error_code")
        run.completed_at = datetime.utcnow()
        db.add(run); db.commit()
        db.expire(conversation)
        conversation = db.query(SalesConversation).filter(
            SalesConversation.id == conversation.id,
        ).populate_existing().with_for_update().one()
        if not reply or result.get("requires_human") or conversation.is_paused or lead.is_opt_out:
            job.status = "cancelled" if conversation.is_paused or lead.is_opt_out else "failed"
            job.processed_at = datetime.utcnow(); db.commit(); return
        await _dispatch(
            db, conversation=conversation, lead=lead, content=reply, role="assistant",
            agent_run_id=run.id, metadata={"event_kind": "scheduled_follow_up", "reason": job.reason},
            idempotency_key=dispatch_key,
        )
        job.status = "processed"; job.processed_at = datetime.utcnow()
        lead.last_interaction_at = datetime.utcnow()
        if lead.pipeline_stage not in {"S07_OBJECTION", "S08_APPOINTMENT", "S09_HANDOFF"}:
            lead.pipeline_stage = "S06_NURTURE"
        _schedule_next_action(db, conversation, lead, event_id)
        db.add_all([job, lead]); db.commit()
    except Exception:
        db.rollback()
        job = db.query(SalesFollowUpJob).filter(SalesFollowUpJob.id == job_id).first()
        if job:
            job.status = "failed" if job.attempt_number >= 3 else "pending"
            job.attempt_number += 1
            job.scheduled_at = datetime.utcnow() + timedelta(minutes=5)
            db.commit()
        raise
    finally:
        db.close()
