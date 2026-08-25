from __future__ import annotations

from datetime import datetime, timedelta
import json
import uuid

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.modules.project_team.service import eligible_sales_assignments
from app.modules.projects.models import Project, ProjectCampaign, ProjectPropertyType, ProjectUnit
from app.modules.sales_crm.models import Lead, Meeting
from app.modules.sales_crm.scheduling import available_slots, create_agent_appointment
from app.modules.users.models import User

from .models import AgentRun, SalesAgentSimulation, SalesConversation, SalesFollowUpJob, SalesMessage
from .service import get_or_create_conversation, simulate_turn


COMPLETED_PROJECT_STATUSES = {"complete", "completed"}
INITIAL_EVENT_PREFIX = "simulation-start:"


def _number(value) -> float | None:
    return float(value) if value is not None else None


def _delivery_timeline(project: Project) -> str | None:
    profile = project.profile
    if not profile:
        return None
    states = profile.field_states or {}
    data = profile.profile_data or {}
    for key in ("delivery_dates", "estimated_delivery", "availability_timeline"):
        state = states.get(key, {})
        value = data.get(key)
        if value and state.get("status") in {"confirmed", "corrected_by_user"}:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return profile.delivery_dates or None


def _property_type_product(item: ProjectPropertyType) -> dict:
    return {
        "id": f"property_type:{item.id}",
        "name": item.name,
        "code": item.code,
        "description": item.description,
        "bedrooms": item.bedrooms,
        "bathrooms": item.bathrooms,
        "area_min": _number(item.area_min),
        "area_max": _number(item.area_max),
        "area_unit": item.area_unit,
        "available_units": item.available_units,
        "total_units": item.total_units,
        "starting_price": _number(item.starting_price),
        "maximum_price": _number(item.maximum_price),
        "currency": item.currency,
        "inventory_updated_at": item.inventory_updated_at,
    }


def _unit_products(db: Session, project_id: str) -> list[dict]:
    """Keep the existing Demo usable when it only has unit-level inventory."""
    units = db.query(ProjectUnit).filter(ProjectUnit.project_id == project_id).order_by(ProjectUnit.typology).all()
    grouped: dict[str, list[ProjectUnit]] = {}
    for unit in units:
        if unit.typology:
            grouped.setdefault(unit.typology, []).append(unit)
    result = []
    for typology, items in grouped.items():
        prices = [item.list_price for item in items if item.list_price is not None]
        areas = [item.area for item in items if item.area is not None]
        available = [item for item in items if item.status == "available"]
        result.append({
            "id": f"unit_typology:{typology}",
            "name": typology,
            "code": None,
            "description": "Available unit typology",
            "bedrooms": next((item.bedrooms for item in items if item.bedrooms is not None), None),
            "bathrooms": next((item.bathrooms for item in items if item.bathrooms is not None), None),
            "area_min": _number(min(areas)) if areas else None,
            "area_max": _number(max(areas)) if areas else None,
            "area_unit": None,
            "available_units": len(available),
            "total_units": len(items),
            "starting_price": _number(min(prices)) if prices else None,
            "maximum_price": _number(max(prices)) if prices else None,
            "currency": next((item.currency for item in items if item.currency), None),
            "inventory_updated_at": max(
                (item.inventory_updated_at for item in items if item.inventory_updated_at),
                default=None,
            ),
        })
    return result


def _products(db: Session, project: Project) -> list[dict]:
    property_types = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == project.id,
        ProjectPropertyType.review_status == "confirmed",
    ).order_by(ProjectPropertyType.sort_order, ProjectPropertyType.name).all()
    return [_property_type_product(item) for item in property_types] or _unit_products(db, project.id)


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
            "products": _products(db, project),
            "delivery_timeline": _delivery_timeline(project),
            "eligible_sales_users": len(eligible_sales_assignments(db, project.id)),
        })
    return result


def create_simulation(
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

    product = _selected_product(db, project=project, product_id=lead_form["product_id"])

    now = datetime.utcnow()
    external_id = f"simulation:{uuid.uuid4()}"
    full_name = f"{lead_form['first_name']} {lead_form['last_name']}".strip()
    budget = {
        "minimum": _number(lead_form["budget_min"]),
        "maximum": _number(lead_form.get("budget_max")),
        "currency": product.get("currency"),
    }
    qualification = {
        "selected_product": product,
        "budget": budget,
        "custom_answers": lead_form.get("custom_answers") or {},
    }
    lead = Lead(
        company_id=company_id,
        project_id=project.id,
        campaign_id=campaign.id,
        full_name=full_name,
        phone=lead_form["phone"],
        email=str(lead_form.get("email")) if lead_form.get("email") else None,
        source="Meta Lead Form Simulation",
        platform="demo_meta_form",
        external_lead_id=external_id,
        preferred_channel="simulation",
        channel_address=lead_form["phone"],
        consent_status="granted_simulation",
        consent_captured_at=now,
        qualification_summary=json.dumps(qualification, ensure_ascii=False, default=str),
        meta_form_data=jsonable_encoder({
            "first_name": lead_form["first_name"],
            "last_name": lead_form["last_name"],
            "phone": lead_form["phone"],
            "email": str(lead_form["email"]),
            "selected_product": product,
            "budget": budget,
            "custom_answers": lead_form.get("custom_answers") or {},
        }),
        visit_recommendations=(
            f"Review the lead's interest in {product.get('name') or 'the selected property'} and "
            "confirm priorities, budget fit and any unresolved questions before the visit."
        ),
        agent_status="initializing",
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
        status="initializing",
        form_snapshot=jsonable_encoder({
            "first_name": lead_form["first_name"],
            "last_name": lead_form["last_name"],
            "full_name": full_name,
            "phone": lead_form["phone"],
            "email": str(lead_form["email"]),
            "selected_product": product,
            "budget": budget,
            "consent": True,
            "custom_answers": lead_form.get("custom_answers") or {},
        }),
        virtual_now=now,
    )
    db.add(simulation)
    db.commit()
    db.refresh(simulation)

    return {
        "simulation_id": simulation.id,
        "lead_id": lead.id,
        "conversation_id": conversation.id,
        "status": simulation.status,
        "initial_reply": None,
        "prompt_snapshot": {},
        "requires_initial_message": True,
    }


async def generate_initial_message(
    db: Session,
    *,
    company_id: str,
    simulation_id: str,
) -> dict:
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    event_prefix = f"{INITIAL_EVENT_PREFIX}{simulation.id}"
    completed = db.query(AgentRun).filter(
        AgentRun.conversation_id == simulation.conversation_id,
        AgentRun.event_id.like(f"{event_prefix}%"),
        AgentRun.status.in_(("completed", "blocked")),
    ).order_by(AgentRun.started_at.desc()).first()
    if completed:
        result = await simulate_turn(
            db,
            company_id=company_id,
            lead_id=simulation.lead_id,
            inbound_text=_initial_instruction(),
            event_id=completed.event_id,
            record_inbound=False,
            event_kind="lead_form_submitted",
            virtual_now=simulation.virtual_now,
        )
        lead = db.query(Lead).filter(Lead.id == simulation.lead_id).one()
        simulation.prompt_snapshot = completed.prompt_snapshot or {}
        simulation.status = "active" if result.get("reply") else "needs_retry"
        simulation.updated_at = datetime.utcnow()
        lead.agent_status = "simulation" if result.get("reply") else "needs_retry"
        db.add_all([simulation, lead])
        db.commit()
        return result

    if simulation.status == "generating" and simulation.updated_at:
        if datetime.utcnow() - simulation.updated_at < timedelta(minutes=5):
            raise HTTPException(status_code=409, detail="The first SMS is already being generated.")

    failed_attempts = db.query(AgentRun).filter(
        AgentRun.conversation_id == simulation.conversation_id,
        AgentRun.event_id.like(f"{event_prefix}%"),
        AgentRun.status == "failed",
    ).count()
    event_id = event_prefix if failed_attempts == 0 else f"{event_prefix}:retry:{failed_attempts}"
    lead = db.query(Lead).filter(
        Lead.id == simulation.lead_id,
        Lead.company_id == company_id,
    ).one()
    simulation.status = "generating"
    simulation.updated_at = datetime.utcnow()
    lead.agent_status = "generating"
    db.add_all([simulation, lead])
    db.commit()
    try:
        result = await simulate_turn(
            db,
            company_id=company_id,
            lead_id=lead.id,
            inbound_text=_initial_instruction(),
            event_id=event_id,
            record_inbound=False,
            event_kind="lead_form_submitted",
            virtual_now=simulation.virtual_now,
        )
    except Exception:
        db.rollback()
        simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
        lead = db.query(Lead).filter(Lead.id == simulation.lead_id).one()
        simulation.status = "needs_retry"
        simulation.updated_at = datetime.utcnow()
        lead.agent_status = "needs_retry"
        db.add_all([simulation, lead])
        db.commit()
        raise

    run = db.query(AgentRun).filter(AgentRun.id == result["run_id"]).first()
    simulation = _simulation(db, company_id=company_id, simulation_id=simulation_id)
    lead = db.query(Lead).filter(Lead.id == simulation.lead_id).one()
    simulation.prompt_snapshot = run.prompt_snapshot if run else {}
    simulation.status = "active" if result.get("reply") else "needs_retry"
    simulation.updated_at = datetime.utcnow()
    lead.agent_status = "simulation" if result.get("reply") else "needs_retry"
    db.add_all([simulation, lead])
    db.commit()
    return result


def _selected_product(db: Session, *, project: Project, product_id: str) -> dict:
    if product_id.startswith("property_type:"):
        item_id = product_id.removeprefix("property_type:")
        item = db.query(ProjectPropertyType).filter(
            ProjectPropertyType.id == item_id,
            ProjectPropertyType.project_id == project.id,
            ProjectPropertyType.review_status == "confirmed",
        ).first()
        if item:
            return _property_type_product(item)
    elif product_id.startswith("unit_typology:"):
        typology = product_id.removeprefix("unit_typology:")
        for product in _unit_products(db, project.id):
            if product["id"] == product_id and product["name"] == typology:
                return product
    raise HTTPException(
        status_code=422,
        detail="Select a confirmed property type from the chosen Project.",
    )


def _initial_instruction() -> str:
    return (
        "A lead has just submitted the simulated Meta form for this campaign. "
        "Send the approved opening SMS. Use the selected product and budget already present in lead context. "
        "Do not claim the lead provided a purchase timeline. Identify the company and ask at most one useful question."
    )


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
            follow_up_hours=24 if job.attempt_number == 1 else 48,
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
