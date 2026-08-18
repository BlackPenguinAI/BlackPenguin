from __future__ import annotations

from datetime import datetime, timedelta
import json
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.project_team.service import eligible_sales_assignments
from app.modules.projects.models import Project, ProjectCampaign
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.sales_crm.scheduling import available_slots, create_agent_appointment
from app.modules.users.models import User

from .models import AgentRun, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage
from .service import get_or_create_conversation, simulate_turn


COMPLETED_PROJECT_STATUSES = {"complete", "completed"}


def simulation_options(db: Session, *, company_id: str) -> list[dict]:
    projects = db.query(Project).filter(
        Project.company_id == company_id,
        Project.is_active.is_(True),
    ).order_by(Project.name).all()
    result = []
    for project in projects:
        approved = bool(project.is_demo or (project.profile and project.profile.final_approved))
        if project.onboarding_status not in COMPLETED_PROJECT_STATUSES or not approved:
            continue
        campaigns = db.query(ProjectCampaign).filter(
            ProjectCampaign.project_id == project.id,
        ).order_by(ProjectCampaign.created_at).all()
        result.append({
            "id": project.id,
            "name": project.name,
            "onboarding_status": project.onboarding_status,
            "campaigns": [{
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "objective": item.objective,
            } for item in campaigns],
            "eligible_sales_users": len(eligible_sales_assignments(db, project.id)),
        })
    return result


async def create_simulation(
    db: Session,
    *,
    company_id: str,
    created_by_user_id: str,
    project_id: str,
    campaign_id: str,
    lead_form: dict,
) -> dict:
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.company_id == company_id,
        Project.is_active.is_(True),
    ).first()
    approved = bool(project and (project.is_demo or (project.profile and project.profile.final_approved)))
    if not project or project.onboarding_status not in COMPLETED_PROJECT_STATUSES or not approved:
        raise HTTPException(status_code=409, detail="Select a Project with completed and approved onboarding.")
    campaign = db.query(ProjectCampaign).filter(
        ProjectCampaign.id == campaign_id,
        ProjectCampaign.project_id == project.id,
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found for this Project.")
    if not lead_form.get("consent"):
        raise HTTPException(status_code=422, detail="Communication consent is required for the SMS simulation.")

    now = datetime.utcnow()
    external_id = f"simulation:{uuid.uuid4()}"
    qualification = {
        key: value for key, value in {
            "product_interest": lead_form.get("product_interest"),
            "budget": lead_form.get("budget"),
            "purchase_timeline": lead_form.get("purchase_timeline"),
            "custom_answers": lead_form.get("custom_answers") or {},
        }.items() if value
    }
    lead = Lead(
        company_id=company_id,
        project_id=project.id,
        campaign_id=campaign.id,
        full_name=lead_form["full_name"],
        phone=lead_form["phone"],
        email=str(lead_form.get("email")) if lead_form.get("email") else None,
        source="Meta Lead Form Simulation",
        platform="demo_meta_form",
        external_lead_id=external_id,
        preferred_channel="simulation",
        channel_address=lead_form["phone"],
        consent_status="granted_simulation",
        consent_captured_at=now,
        qualification_summary=json.dumps(qualification, ensure_ascii=False) if qualification else None,
        agent_status="simulation",
        is_demo=True,
    )
    db.add(lead)
    db.flush()
    conversation = get_or_create_conversation(db, lead, channel="simulation")
    conversation.is_paused = False
    conversation.pause_reason = None
    simulation = SalesAgentSimulation(
        company_id=company_id,
        project_id=project.id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        conversation_id=conversation.id,
        created_by_user_id=created_by_user_id,
        form_snapshot={**lead_form, "email": str(lead_form.get("email")) if lead_form.get("email") else None},
        virtual_now=now,
    )
    db.add(simulation)
    db.commit()
    db.refresh(simulation)

    result = await simulate_turn(
        db,
        company_id=company_id,
        lead_id=lead.id,
        inbound_text=(
            "A lead has just submitted the simulated Meta form for this campaign. "
            "Send the approved opening SMS. Use the form facts already present in lead context, "
            "identify the company, and ask at most one useful question."
        ),
        event_id=f"simulation-start:{simulation.id}",
        record_inbound=False,
        event_kind="lead_form_submitted",
        virtual_now=simulation.virtual_now,
    )
    run = db.query(AgentRun).filter(AgentRun.id == result["run_id"]).first()
    simulation.prompt_snapshot = run.prompt_snapshot if run else {}
    simulation.updated_at = datetime.utcnow()
    db.add(simulation)
    db.commit()
    return {
        "simulation_id": simulation.id,
        "lead_id": lead.id,
        "conversation_id": conversation.id,
        "status": simulation.status,
        "initial_reply": result.get("reply"),
        "prompt_snapshot": simulation.prompt_snapshot or {},
    }


def slots_for_simulation(
    db: Session,
    *,
    company_id: str,
    simulation_id: str,
    duration_minutes: int = 45,
) -> list[dict]:
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    return available_slots(
        db,
        project_id=simulation.project_id,
        after=simulation.virtual_now,
        duration_minutes=duration_minutes,
    )


def confirm_simulation_appointment(
    db: Session,
    *,
    company_id: str,
    simulation_id: str,
    starts_at: datetime,
    duration_minutes: int,
    modality: str,
) -> dict:
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    if simulation.status == "appointment_confirmed":
        meeting = db.query(Meeting).filter(
            Meeting.lead_id == simulation.lead_id,
            Meeting.source == "agent_simulation",
        ).first()
        if not meeting:
            raise HTTPException(status_code=409, detail="The simulation appointment state is inconsistent.")
        user = db.query(User).filter(User.id == meeting.assigned_sales_user_id).one()
        return _appointment_response(meeting, user)
    lead = db.query(Lead).filter(
        Lead.id == simulation.lead_id,
        Lead.company_id == company_id,
    ).one()
    meeting, user = create_agent_appointment(
        db,
        lead=lead,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        modality=modality,
    )
    sales_name = " ".join(value for value in (user.first_name, user.last_name) if value) or user.email
    db.add(SalesMessage(
        conversation_id=simulation.conversation_id,
        channel="simulation",
        direction="inbound",
        role="user",
        content=f"Yes, {starts_at.isoformat(timespec='minutes')} works for me.",
        status="received",
        created_at=simulation.virtual_now,
    ))
    db.add(SalesMessage(
        conversation_id=simulation.conversation_id,
        channel="simulation",
        direction="outbound",
        role="assistant",
        content=(
            f"Your appointment is confirmed for {starts_at.strftime('%A, %B %d at %H:%M')} "
            f"with {sales_name}. We look forward to speaking with you."
        ),
        status="simulated",
        created_at=simulation.virtual_now + timedelta(seconds=1),
    ))
    conversation = db.query(SalesConversation).filter(SalesConversation.id == simulation.conversation_id).one()
    conversation.stage = "appointment_confirmed"
    conversation.updated_at = simulation.virtual_now
    simulation.status = "appointment_confirmed"
    simulation.updated_at = datetime.utcnow()
    lead.next_action_at = None
    db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == simulation.conversation_id,
        SalesFollowUpJob.status == "pending",
    ).update({SalesFollowUpJob.status: "cancelled"}, synchronize_session=False)
    db.add_all([conversation, simulation, lead])
    db.commit()
    db.refresh(meeting)
    return _appointment_response(meeting, user)


async def advance_simulation(
    db: Session,
    *,
    company_id: str,
    simulation_id: str,
    hours: int,
) -> dict:
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    if simulation.status != "active":
        raise HTTPException(status_code=409, detail="Only active simulations can advance time.")
    simulation.virtual_now += timedelta(hours=hours)
    db.add(simulation)
    db.commit()
    jobs = db.query(SalesFollowUpJob).filter(
        SalesFollowUpJob.conversation_id == simulation.conversation_id,
        SalesFollowUpJob.status == "pending",
        SalesFollowUpJob.scheduled_at <= simulation.virtual_now,
    ).order_by(SalesFollowUpJob.scheduled_at).all()
    processed = 0
    for job in jobs:
        lead = db.query(Lead).filter(Lead.id == simulation.lead_id).one()
        if lead.is_opt_out or db.query(Meeting).filter(Meeting.lead_id == lead.id).first():
            job.status = "cancelled"
            db.add(job)
            db.commit()
            continue
        job.status = "processed"
        job.processed_at = simulation.virtual_now
        db.add(job)
        db.commit()
        await simulate_turn(
            db,
            company_id=company_id,
            lead_id=lead.id,
            inbound_text=(
                f"The lead has not replied. This is follow-up attempt {job.attempt_number}. "
                "Write one concise SMS that follows the approved cadence and does not repeat the previous message."
            ),
            event_id=f"followup:{job.id}",
            record_inbound=False,
            event_kind="follow_up",
            virtual_now=simulation.virtual_now,
        )
        processed += 1
    db.refresh(simulation)
    return {"virtual_now": simulation.virtual_now, "processed_follow_ups": processed}


def approve_simulation(
    db: Session,
    *,
    company_id: str,
    simulation_id: str,
    status: str,
    notes: str | None,
) -> SalesAgentSimulation:
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    simulation.approval_status = status
    simulation.approval_notes = notes
    simulation.updated_at = datetime.utcnow()
    db.add(simulation)
    db.commit()
    db.refresh(simulation)
    return simulation


def _simulation(db: Session, *, company_id: str, simulation_id: str) -> SalesAgentSimulation:
    item = db.query(SalesAgentSimulation).filter(
        SalesAgentSimulation.id == simulation_id,
        SalesAgentSimulation.company_id == company_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    return item


def _appointment_response(meeting: Meeting, user: User) -> dict:
    name = " ".join(value for value in (user.first_name, user.last_name) if value) or user.email
    return {
        "meeting_id": meeting.id,
        "assigned_sales_user_id": user.id,
        "assigned_sales_name": name,
        "meeting_time": meeting.meeting_time,
        "calendar_sync_status": meeting.calendar_sync_status,
    }
