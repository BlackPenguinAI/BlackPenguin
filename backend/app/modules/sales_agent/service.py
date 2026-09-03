from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import calendar
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import FunnelStage, Lead, Meeting
from app.modules.sales_crm.scheduling import available_slots, create_agent_appointment, next_cadence_time
from app.modules.sales_crm.calendar_links import calendar_invite_url, google_calendar_add_url

from .graph import GRAPH_VERSION, TOOLSET_VERSION, build_sales_graph
from .models import AgentRun, OutboundMessage, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage


MONTHS = {
    name.lower(): index
    for index in range(1, 13)
    for name in (calendar.month_name[index], calendar.month_abbr[index])
}


def _project_zone(project: Project) -> ZoneInfo:
    try:
        return ZoneInfo(project.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _requested_date(text: str, *, now: datetime, zone: ZoneInfo) -> date | None:
    """Resolve an explicit date without inventing one when the lead did not provide it."""
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    lowered = text.lower()
    month_match = re.search(
        r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        lowered,
    )
    local_now = now.replace(tzinfo=timezone.utc).astimezone(zone)
    if month_match:
        month = MONTHS[month_match.group(1)]
        year = local_now.year + (1 if month < local_now.month else 0)
        try:
            return date(year, month, int(month_match.group(2)))
        except ValueError:
            return None
    ordinal = re.search(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", lowered)
    if not ordinal:
        return None
    day = int(ordinal.group(1))
    year, month = local_now.year, local_now.month
    for _ in range(2):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate and candidate >= local_now.date():
            return candidate
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return None


def _action_types(actions: list[dict] | None) -> set[str]:
    return {
        str(action.get("type"))
        for action in (actions or [])
        if isinstance(action, dict) and action.get("type")
    }


def _is_availability_request(text: str, *, now: datetime, zone: ZoneInfo) -> bool:
    """Detect scheduling turns independently from the model's optional tool action."""
    lowered = text.casefold()
    scheduling_words = (
        "appointment", "schedule", "availability", "available", "slot", "visit",
        "cita", "agendar", "horario", "disponible", "visita",
    )
    return any(word in lowered for word in scheduling_words) or _requested_date(text, now=now, zone=zone) is not None


def _availability_reply(
    db: Session, *, project: Project, inbound_text: str, now: datetime,
) -> tuple[str, list[datetime]]:
    """Execute the model's slot request and return a complete, grounded SMS."""
    zone = _project_zone(project)
    requested = _requested_date(inbound_text, now=now, zone=zone)
    search_after = now
    days = 14
    if requested:
        local_midnight = datetime.combine(requested, time.min, tzinfo=zone)
        search_after = local_midnight.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(microseconds=1)
        days = 2
    slots = available_slots(
        db,
        project_id=project.id,
        after=search_after,
        duration_minutes=45,
        days=days,
        limit=48 if requested else 3,
    )
    if requested:
        slots = [
            slot for slot in slots
            if slot["start_at"].replace(tzinfo=timezone.utc).astimezone(zone).date() == requested
        ]
    slots = slots[:3]
    if not slots:
        when = requested.strftime("%A, %B %-d") if requested else "the next 14 days"
        return (
            f"I couldn't find a verified appointment time for {when}. "
            "Would you like another day, or should I ask the sales team to contact you?",
            [],
        )
    local_starts = [slot["start_at"].replace(tzinfo=timezone.utc).astimezone(zone) for slot in slots]
    day_label = local_starts[0].strftime("%A, %B %-d")
    times = [value.strftime("%-I:%M %p") for value in local_starts]
    time_list = times[0] if len(times) == 1 else f"{', '.join(times[:-1])} or {times[-1]}"
    zone_label = _timezone_label(slots[0]["start_at"], zone, project.timezone or "UTC")
    return (
        f"I found these verified appointment times for {day_label}: {time_list} "
        f"({zone_label}, Project local time). Which one works best for you?",
        [slot["start_at"] for slot in slots],
    )


def _selected_time(text: str) -> time | None:
    match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
        if not match:
            return None
        return time(int(match.group(1)), int(match.group(2)))
    hour = int(match.group(1)) % 12
    if match.group(3).lower().startswith("p"):
        hour += 12
    minute = int(match.group(2) or 0)
    if minute > 59:
        return None
    return time(hour, minute)


def _offered_slot_selection(
    db: Session,
    *,
    conversation_id: str,
    inbound_text: str,
    project: Project,
    now: datetime,
) -> datetime | None:
    """Resolve a choice only against a recent verified offer from this chat."""
    selected = _selected_time(inbound_text)
    if selected is None:
        return None
    zone = _project_zone(project)
    messages = db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation_id,
        SalesMessage.direction == "outbound",
    ).order_by(SalesMessage.created_at.desc()).limit(20).all()
    for message in messages:
        offer = (message.metadata_json or {}).get("appointment_offer")
        if not isinstance(offer, dict):
            continue
        for raw_slot in offer.get("slots", []):
            try:
                start_utc = datetime.fromisoformat(raw_slot)
            except (TypeError, ValueError):
                continue
            local_start = start_utc.replace(tzinfo=timezone.utc).astimezone(zone)
            if local_start.time().replace(second=0, microsecond=0) == selected:
                return start_utc.replace(tzinfo=None)
        # Only the latest structured offer is actionable. Older offers may have
        # been superseded by a different date or refreshed availability.
        return None

    # Backward-compatible fallback for offers created before slot metadata was
    # introduced. It is deliberately limited to a verified-offer SMS.
    legacy_offer = next(
        (message for message in messages if "verified appointment times" in message.content.casefold()),
        None,
    )
    if not legacy_offer:
        return None
    requested = _requested_date(legacy_offer.content, now=now, zone=zone)
    if requested is None:
        return None
    advertised_times = {_selected_time(value) for value in re.findall(
        r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)",
        legacy_offer.content,
        flags=re.IGNORECASE,
    )}
    if selected not in advertised_times:
        return None
    local_start = datetime.combine(requested, selected, tzinfo=zone)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _timezone_label(value: datetime, zone: ZoneInfo, timezone_name: str) -> str:
    local = value.replace(tzinfo=timezone.utc).astimezone(zone)
    offset = local.strftime("%z")
    formatted_offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC+00:00"
    return f"{formatted_offset}, {timezone_name}"


def _appointment_confirmation(
    *, project: Project, lead: Lead, user, starts_at: datetime,
) -> str:
    zone = _project_zone(project)
    local_start = starts_at.replace(tzinfo=timezone.utc).astimezone(zone)
    sales_name = " ".join(
        value for value in (user.first_name, user.last_name) if value
    ) or user.email
    location_parts = [project.address, project.city, project.country]
    location = ", ".join(dict.fromkeys(value.strip() for value in location_parts if value and value.strip()))
    location = f"{project.name}, {location}" if location else project.name
    email = lead.email or "the email address provided in your lead form"
    return (
        f"Your appointment is confirmed for {local_start.strftime('%A, %B %-d, %Y at %-I:%M %p')} "
        f"({_timezone_label(starts_at, zone, project.timezone or 'UTC')}). "
        f"Your Sales representative is {sales_name}. Location: {location}. "
        f"A confirmation with these appointment details will also be sent to {email}. "
        "We look forward to welcoming you!"
    )


def conversation_summaries(
    db: Session,
    *,
    company_id: str,
    project_id: str | None = None,
    sales_user_id: str | None = None,
    allowed_project_ids: list[str] | None = None,
) -> list[dict]:
    query = db.query(SalesConversation, Lead, Project).join(
        Lead, Lead.id == SalesConversation.lead_id,
    ).join(Project, Project.id == SalesConversation.project_id).filter(
        SalesConversation.company_id == company_id,
    )
    if project_id:
        query = query.filter(SalesConversation.project_id == project_id)
    if allowed_project_ids is not None:
        query = query.filter(SalesConversation.project_id.in_(allowed_project_ids)) if allowed_project_ids else query.filter(SalesConversation.project_id == "")
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    rows = query.order_by(SalesConversation.updated_at.desc()).all()
    result = []
    for conversation, lead, project in rows:
        last = db.query(SalesMessage).filter(
            SalesMessage.conversation_id == conversation.id,
        ).order_by(SalesMessage.created_at.desc()).first()
        simulation = db.query(SalesAgentSimulation).filter(
            SalesAgentSimulation.conversation_id == conversation.id,
        ).first()
        campaign = db.query(ProjectCampaign).filter(ProjectCampaign.id == conversation.campaign_id).first() if conversation.campaign_id else None
        meeting = db.query(Meeting).filter(Meeting.lead_id == lead.id).order_by(Meeting.created_at.desc()).first()
        result.append({
            "id": conversation.id, "lead_id": lead.id, "project_id": project.id,
            "campaign_id": conversation.campaign_id, "channel": conversation.channel,
            "stage": conversation.stage, "automation_level": conversation.automation_level,
            "is_paused": conversation.is_paused, "updated_at": conversation.updated_at,
            "lead_name": lead.full_name, "phone": lead.phone,
            "funnel_stage": lead.funnel_stage.value if hasattr(lead.funnel_stage, "value") else str(lead.funnel_stage),
            "intent_score": float(lead.intent_score or 0),
            "intent_tier": lead.intent_tier, "assigned_segment": lead.assigned_segment,
            "pipeline_stage": lead.pipeline_stage, "pause_reason": conversation.pause_reason,
            "last_message": last.content if last else None,
            "last_message_at": last.created_at if last else None,
            "next_action_at": lead.next_action_at, "agent_status": lead.agent_status,
            "project_name": project.name, "is_demo": bool(project.is_demo), "is_test": bool(lead.is_test),
            "campaign_name": campaign.name if campaign else None,
            "simulation_id": simulation.id if simulation else None,
            "simulation_status": simulation.status if simulation else None,
            "approval_status": simulation.approval_status if simulation else None,
            "virtual_now": simulation.virtual_now if simulation else None,
            "appointment_id": meeting.id if meeting else None,
            "assigned_sales_user_id": lead.assigned_sales_user_id,
        })
    return result


def conversation_messages(
    db: Session, *, company_id: str, conversation_id: str, sales_user_id: str | None = None,
) -> list[SalesMessage]:
    query = db.query(SalesConversation).join(Lead, Lead.id == SalesConversation.lead_id).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    conversation = query.first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    # A lead message and its generated answer can share virtual time. Direction
    # preserves the causal order before the stable id tie-breaker.
    return db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation.id,
    ).order_by(
        SalesMessage.created_at.asc(),
        case((SalesMessage.direction == "inbound", 0), else_=1),
        SalesMessage.id.asc(),
    ).all()


def set_conversation_action(
    db: Session, *, company_id: str, conversation_id: str, action: str,
    sales_user_id: str | None = None,
) -> SalesConversation:
    query = db.query(SalesConversation).join(Lead, Lead.id == SalesConversation.lead_id).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == company_id,
    )
    if sales_user_id:
        query = query.filter(Lead.assigned_sales_user_id == sales_user_id)
    conversation = query.first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if action == "resume":
        lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
        if lead and lead.is_opt_out:
            raise HTTPException(status_code=409, detail="An opted-out lead cannot be resumed.")
        if conversation.pause_reason == "Appointment confirmed":
            raise HTTPException(status_code=409, detail="This conversation is closed because the appointment is confirmed.")
        conversation.is_paused = False
        conversation.pause_reason = None
        if lead:
            lead.agent_status = "active" if conversation.channel == "sms" else "simulation"
            if conversation.channel == "sms" and not db.query(SalesFollowUpJob).filter(
                SalesFollowUpJob.conversation_id == conversation.id,
                SalesFollowUpJob.status == "pending",
            ).first():
                hours = {"hot": 24, "warm": 72, "cold": 24 * 14}.get(lead.intent_tier, 72)
                project = db.query(Project).filter(Project.id == conversation.project_id).first()
                scheduled_at = next_cadence_time(
                    now=datetime.utcnow(), timezone_name=project.timezone if project else "UTC", delay_hours=hours,
                )
                db.add(SalesFollowUpJob(
                    conversation_id=conversation.id,
                    idempotency_key=f"resume:{conversation.id}:{uuid.uuid4()}",
                    scheduled_at=scheduled_at, reason=f"{lead.intent_tier}_cadence", attempt_number=1,
                ))
                lead.next_action_at = scheduled_at
    else:
        conversation.is_paused = True
        conversation.pause_reason = "Human handoff requested" if action == "human_handoff" else "Paused by user"
        db.query(SalesFollowUpJob).filter(
            SalesFollowUpJob.conversation_id == conversation.id,
            SalesFollowUpJob.status == "pending",
        ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
        lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
        if lead:
            lead.agent_status = "human_control" if action in {"pause", "human_handoff"} else lead.agent_status
            lead.next_action_at = None
    conversation.updated_at = datetime.utcnow()
    db.add(conversation); db.commit(); db.refresh(conversation)
    return conversation


def get_or_create_conversation(db: Session, lead: Lead, *, channel: str) -> SalesConversation:
    conversation = db.query(SalesConversation).filter(
        SalesConversation.lead_id == lead.id,
        SalesConversation.channel == channel,
    ).first()
    if conversation:
        return conversation
    conversation = SalesConversation(
        company_id=lead.company_id,
        project_id=lead.project_id,
        campaign_id=lead.campaign_id,
        lead_id=lead.id,
        channel=channel,
        automation_level=0,
        is_paused=True,
        pause_reason="Simulation/draft mode",
    )
    db.add(conversation)
    db.flush()
    return conversation


async def simulate_turn(
    db: Session,
    *,
    company_id: str,
    lead_id: str,
    inbound_text: str,
    event_id: str | None = None,
    record_inbound: bool = True,
    event_kind: str = "lead_message",
    follow_up_hours: int | None = None,
    virtual_now: datetime | None = None,
    sales_user_id: str | None = None,
) -> dict:
    lead_query = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id)
    if sales_user_id:
        lead_query = lead_query.filter(Lead.assigned_sales_user_id == sales_user_id)
    lead = lead_query.first()
    if not lead or not lead.project_id:
        raise HTTPException(status_code=404, detail="Lead not found or not associated with a Project.")
    project = db.query(Project).filter(Project.id == lead.project_id, Project.company_id == company_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not lead.is_demo:
        raise HTTPException(status_code=409, detail="This endpoint accepts simulation leads only.")
    event_id = event_id or f"simulation:{uuid.uuid4()}"
    existing = db.query(AgentRun).filter(AgentRun.event_id == event_id).first()
    if existing:
        output = existing.output_snapshot or {}
        return _response(existing, output)

    conversation = get_or_create_conversation(db, lead, channel="simulation")
    simulation = db.query(SalesAgentSimulation).filter(
        SalesAgentSimulation.lead_id == lead.id,
        SalesAgentSimulation.conversation_id == conversation.id,
    ).first()
    if virtual_now is not None:
        now = virtual_now
    elif simulation:
        # Once +24h/+48h advances the simulation, wall-clock timestamps would
        # place later replies before the reminder. The simulation clock is the
        # sole authority here: mixing in wall time also changes relative dates
        # such as "Monday, the 31st" when replaying a past/future scenario.
        now = simulation.virtual_now + timedelta(seconds=1)
        simulation.virtual_now = now
        db.add(simulation)
    else:
        now = datetime.utcnow()
    latest_message_at = db.query(func.max(SalesMessage.created_at)).filter(
        SalesMessage.conversation_id == conversation.id,
    ).scalar()
    message_now = (
        max(now, latest_message_at + timedelta(seconds=1))
        if latest_message_at else now
    )
    conversation.is_paused = False
    conversation.pause_reason = None
    conversation.updated_at = message_now
    lead.last_interaction_at = message_now
    if lead.funnel_stage == FunnelStage.NEW:
        lead.funnel_stage = FunnelStage.CONTACTED
        lead.stage_changed_at = now
    if record_inbound:
        db.add(SalesMessage(
            conversation_id=conversation.id,
            channel="simulation",
            direction="inbound",
            role="user",
            content=inbound_text,
            status="received",
            created_at=message_now,
        ))
    normalized = inbound_text.strip().upper()
    if record_inbound and normalized in {"STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}:
        lead.is_opt_out = True
        lead.consent_status = "opted_out"
        lead.agent_status = "paused"
        lead.next_action_at = None
        conversation.is_paused = True
        conversation.pause_reason = "Lead opted out"
        db.query(SalesFollowUpJob).filter(
            SalesFollowUpJob.conversation_id == conversation.id,
            SalesFollowUpJob.status == "pending",
        ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
        db.add(SalesMessage(
            conversation_id=conversation.id,
            channel="simulation",
            direction="outbound",
            role="assistant",
            content="You have been unsubscribed and will not receive further messages.",
            status="simulated",
            created_at=message_now + timedelta(microseconds=1),
        ))
        db.commit()
        return {
            "run_id": f"optout:{conversation.id}", "conversation_id": conversation.id,
            "status": "completed", "mode": "simulation",
            "reply": "You have been unsubscribed and will not receive further messages.",
            "intent": "opt_out", "proposed_actions": [], "requires_human": False,
            "policy_violations": [], "draft_id": None,
        }
    run = AgentRun(
        conversation_id=conversation.id,
        event_id=event_id,
        mode="simulation",
        status="running",
        graph_version=GRAPH_VERSION,
        toolset_version=TOOLSET_VERSION,
        prompt_snapshot={},
        model="pending",
        input_snapshot={"lead_id": lead.id, "message": inbound_text, "event_kind": event_kind},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        result = await build_sales_graph(db).ainvoke({
            "event_id": event_id,
            "mode": "simulation",
            "conversation_id": conversation.id,
            "company_id": company_id,
            "project_id": project.id,
            "campaign_id": lead.campaign_id,
            "lead_id": lead.id,
            "channel": "simulation",
            "inbound_text": inbound_text,
            "event_kind": event_kind,
            "requires_human": False,
            "policy_violations": [],
        })
        proposed_actions = result.get("proposed_actions", [])
        proposed_reply = result.get("proposed_reply")
        availability_handled = False
        appointment_confirmed = False
        offered_slots: list[datetime] = []
        selected_slot = _offered_slot_selection(
            db,
            conversation_id=conversation.id,
            inbound_text=inbound_text,
            project=project,
            now=now,
        ) if record_inbound and event_kind == "lead_message" else None
        if not result.get("policy_violations") and selected_slot is not None:
            try:
                meeting, assigned_user = create_agent_appointment(
                    db,
                    lead=lead,
                    starts_at=selected_slot,
                    duration_minutes=45,
                    modality="showroom",
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                selected_local = selected_slot.replace(tzinfo=timezone.utc).astimezone(_project_zone(project))
                proposed_reply, offered_slots = _availability_reply(
                    db,
                    project=project,
                    inbound_text=selected_local.strftime("%B %-d, %Y"),
                    now=now,
                )
                proposed_reply = (
                    "That appointment time was just booked by another lead. "
                    + proposed_reply
                )
                proposed_actions = [{"type": "request_available_slots"}]
                if offered_slots:
                    proposed_actions.append({"type": "offer_appointment"})
            else:
                proposed_reply = _appointment_confirmation(
                    project=project,
                    lead=lead,
                    user=assigned_user,
                    starts_at=meeting.meeting_time,
                )
                proposed_reply += (
                    f" Add to Google Calendar: {google_calendar_add_url(project=project, lead=lead, starts_at=meeting.meeting_time)}. "
                    f"Other calendar apps: {calendar_invite_url(meeting.id)}"
                )
                proposed_actions = [{
                    "type": "appointment_confirmed",
                    "meeting_id": meeting.id,
                    "assigned_sales_user_id": assigned_user.id,
                }]
                appointment_confirmed = True
                conversation.stage = "appointment_confirmed"
                conversation.is_paused = True
                conversation.pause_reason = "Appointment confirmed"
                lead.agent_status = "appointment_confirmed"
                lead.pipeline_stage = "S09_HANDOFF"
                lead.next_action_at = None
                if simulation:
                    simulation.status = "appointment_confirmed"
                    simulation.updated_at = datetime.utcnow()
                    db.add(simulation)
                db.query(SalesFollowUpJob).filter(
                    SalesFollowUpJob.conversation_id == conversation.id,
                    SalesFollowUpJob.status == "pending",
                ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
            availability_handled = True
        elif not result.get("policy_violations") and (
            "request_available_slots" in _action_types(proposed_actions)
            or _is_availability_request(inbound_text, now=now, zone=_project_zone(project))
        ):
            proposed_reply, offered_slots = _availability_reply(
                db, project=project, inbound_text=inbound_text, now=now,
            )
            availability_handled = True
            proposed_actions = [
                action for action in proposed_actions
                if isinstance(action, dict) and action.get("type") != "request_human_review"
            ]
            if "request_available_slots" not in _action_types(proposed_actions):
                proposed_actions.append({"type": "request_available_slots"})
            if offered_slots and "offer_appointment" not in _action_types(proposed_actions):
                proposed_actions.append({"type": "offer_appointment"})
        run.prompt_configuration_id = result.get("prompt_configuration_id")
        run.prompt_snapshot = result.get("prompt_snapshot", {})
        run.model = result.get("model", "unknown")
        run.output_snapshot = {
            "reply": proposed_reply,
            "intent": "appointment_confirmed" if appointment_confirmed else result.get("intent"),
            "proposed_actions": proposed_actions,
            "requires_human": False if availability_handled else result.get("requires_human", False),
            "policy_violations": result.get("policy_violations", []),
            "error_code": result.get("error_code"),
        }
        run.status = "blocked" if result.get("policy_violations") else "completed"
        run.error_code = result.get("error_code")
        run.completed_at = datetime.utcnow()
        draft = None
        if proposed_reply and not result.get("policy_violations"):
            draft = OutboundMessage(
                conversation_id=conversation.id,
                agent_run_id=run.id,
                idempotency_key=f"outbound:{conversation.id}:{event_id}",
                channel="simulation",
                recipient=lead.channel_address or lead.phone,
                content=proposed_reply,
                status="draft",
            )
            db.add(draft)
            db.add(SalesMessage(
                conversation_id=conversation.id,
                channel="simulation",
                direction="outbound",
                role="assistant",
                content=proposed_reply,
                status=f"simulated_follow_up_{follow_up_hours or 24}h" if event_kind == "follow_up" else "simulated",
                metadata_json={
                    "event_kind": event_kind,
                    "follow_up_hours": follow_up_hours,
                    **({
                        "appointment_offer": {
                            "duration_minutes": 45,
                            "project_timezone": project.timezone or "UTC",
                            "slots": [slot.isoformat() for slot in offered_slots],
                        },
                    } if offered_slots else {}),
                    **({"appointment_confirmed": True} if appointment_confirmed else {}),
                },
                created_at=message_now + timedelta(microseconds=1) if record_inbound else message_now,
            ))
            conversation.updated_at = message_now
            lead.agent_status = "appointment_confirmed" if appointment_confirmed else "simulation"
            pending_count = db.query(SalesFollowUpJob).filter(
                SalesFollowUpJob.conversation_id == conversation.id,
                SalesFollowUpJob.status == "pending",
            ).count()
            if pending_count == 0 and not lead.is_opt_out and not appointment_confirmed:
                attempt = 1 if event_kind != "follow_up" else min(3, 1 + db.query(SalesFollowUpJob).filter(
                    SalesFollowUpJob.conversation_id == conversation.id,
                    SalesFollowUpJob.status == "processed",
                ).count())
                if attempt <= 3:
                    scheduled_at = now + timedelta(hours=24 if attempt == 1 else 48)
                    db.add(SalesFollowUpJob(
                        conversation_id=conversation.id,
                        idempotency_key=f"followup:{conversation.id}:{event_id}",
                        scheduled_at=scheduled_at,
                        reason="no_response",
                        attempt_number=attempt,
                    ))
                    lead.next_action_at = scheduled_at
            db.add_all([conversation, lead])
        db.commit()
        db.refresh(run)
        response = _response(run, run.output_snapshot)
        response["draft_id"] = draft.id if draft else None
        return response
    except Exception as exc:
        db.rollback()
        run = db.query(AgentRun).filter(AgentRun.id == run.id).one()
        run.status = "failed"
        run.error_code = type(exc).__name__
        run.completed_at = datetime.utcnow()
        db.commit()
        raise


def _response(run: AgentRun, output: dict) -> dict:
    draft = None
    if run.id:
        # The caller may fill this without triggering an extra query.
        draft = None
    return {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "status": run.status,
        "mode": run.mode,
        "reply": output.get("reply"),
        "intent": output.get("intent"),
        "proposed_actions": output.get("proposed_actions", []),
        "requires_human": bool(output.get("requires_human")),
        "policy_violations": output.get("policy_violations", []),
        "draft_id": draft,
    }
