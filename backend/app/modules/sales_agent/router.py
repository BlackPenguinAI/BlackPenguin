from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users.project_access import project_ids_for_user, require_project_access

from .models import AgentRun, OutboundMessage, SalesAgentSimulation, SalesConversation
from app.modules.sales_crm.models import Lead
from .schemas import (
    AgentRunResponse, AppointmentConfirmationResponse, AppointmentConfirm, AppointmentSlot,
    ConversationAction, ConversationSummary, DraftDecision, LiveMetaTestCreate, LiveMetaTestResponse,
    ManualMessageCreate, SalesMessageResponse,
    SimulationAdvance, SimulationApproval, SimulationCreate, SimulationCreateResponse,
    SimulationOptionProject, SimulationRequest,
)
from .service import conversation_messages, conversation_summaries, set_conversation_action, simulate_turn
from .live_service import send_manual_message
from .live_test_service import create_live_meta_test
from .simulation_service import (
    advance_simulation, approve_simulation, confirm_simulation_appointment,
    create_simulation, generate_initial_message, simulation_options, slots_for_simulation,
)


router = APIRouter()


def _require_simulation_access(db: Session, current_user: User, simulation_id: str) -> None:
    simulation = db.query(SalesAgentSimulation).filter(
        SalesAgentSimulation.id == simulation_id,
        SalesAgentSimulation.company_id == current_user.company_id,
    ).first()
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    require_project_access(db, current_user, simulation.project_id)


@router.get("/simulation-options", response_model=list[SimulationOptionProject])
def get_simulation_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    allowed = set(project_ids_for_user(db, current_user))
    return [item for item in simulation_options(db, company_id=current_user.company_id) if item["id"] in allowed]


@router.post("/simulations", response_model=SimulationCreateResponse, status_code=201)
def start_simulation(
    payload: SimulationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    require_project_access(db, current_user, payload.project_id)
    return create_simulation(
        db,
        company_id=current_user.company_id,
        created_by_user_id=current_user.id,
        project_id=payload.project_id,
        campaign_id=payload.campaign_id,
        lead_form=payload.lead.model_dump(),
    )


@router.post("/meta-test-leads", response_model=LiveMetaTestResponse, status_code=201)
async def start_live_meta_test(
    payload: LiveMetaTestCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    require_project_access(db, current_user, payload.project_id)
    return await create_live_meta_test(
        db,
        company_id=current_user.company_id,
        project_id=payload.project_id,
        campaign_id=payload.campaign_id,
        lead_form=payload.lead.model_dump(),
        idempotency_key=idempotency_key,
    )


@router.post("/simulations/{simulation_id}/initial-message", response_model=AgentRunResponse)
async def start_initial_message(
    simulation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _require_simulation_access(db, current_user, simulation_id)
    return await generate_initial_message(
        db,
        company_id=current_user.company_id,
        simulation_id=simulation_id,
    )


@router.get("/simulations/{simulation_id}/slots", response_model=list[AppointmentSlot])
def simulation_slots(
    simulation_id: str,
    duration_minutes: int = 45,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _require_simulation_access(db, current_user, simulation_id)
    return slots_for_simulation(
        db,
        company_id=current_user.company_id,
        simulation_id=simulation_id,
        duration_minutes=duration_minutes,
    )


@router.post("/simulations/{simulation_id}/appointments", response_model=AppointmentConfirmationResponse)
def confirm_appointment(
    simulation_id: str,
    payload: AppointmentConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _require_simulation_access(db, current_user, simulation_id)
    return confirm_simulation_appointment(
        db,
        company_id=current_user.company_id,
        simulation_id=simulation_id,
        starts_at=payload.start_at,
        duration_minutes=payload.duration_minutes,
        modality=payload.modality,
    )


@router.post("/simulations/{simulation_id}/advance")
async def advance_clock(
    simulation_id: str,
    payload: SimulationAdvance,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    _require_simulation_access(db, current_user, simulation_id)
    return await advance_simulation(
        db,
        company_id=current_user.company_id,
        simulation_id=simulation_id,
        hours=payload.hours,
    )


@router.put("/simulations/{simulation_id}/approval")
def set_simulation_approval(
    simulation_id: str,
    payload: SimulationApproval,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    _require_simulation_access(db, current_user, simulation_id)
    item = approve_simulation(
        db,
        company_id=current_user.company_id,
        simulation_id=simulation_id,
        status=payload.status,
        notes=payload.notes,
    )
    return {"simulation_id": item.id, "approval_status": item.approval_status, "notes": item.approval_notes}


@router.post("/simulate", response_model=AgentRunResponse)
async def simulate(
    payload: SimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.company_id == current_user.company_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    require_project_access(db, current_user, lead.project_id)
    return await simulate_turn(
        db,
        company_id=current_user.company_id,
        lead_id=payload.lead_id,
        inbound_text=payload.message,
        event_id=payload.event_id,
        sales_user_id=None,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def conversations(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    if project_id:
        require_project_access(db, current_user, project_id)
    return conversation_summaries(
        db, company_id=current_user.company_id, project_id=project_id,
        sales_user_id=None, allowed_project_ids=project_ids_for_user(db, current_user),
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[SalesMessageResponse])
def messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    conversation = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == current_user.company_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    require_project_access(db, current_user, conversation.project_id)
    return conversation_messages(
        db, company_id=current_user.company_id, conversation_id=conversation_id,
        sales_user_id=None,
    )


@router.post("/conversations/{conversation_id}/action", response_model=ConversationSummary)
def conversation_action(
    conversation_id: str, payload: ConversationAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT])),
):
    existing = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == current_user.company_id,
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    require_project_access(db, current_user, existing.project_id)
    conversation = set_conversation_action(
        db, company_id=current_user.company_id, conversation_id=conversation_id, action=payload.action,
        sales_user_id=None,
    )
    return next(item for item in conversation_summaries(
        db, company_id=current_user.company_id,
        sales_user_id=None, allowed_project_ids=project_ids_for_user(db, current_user),
    ) if item["id"] == conversation.id)


@router.post("/conversations/{conversation_id}/manual-message", response_model=SalesMessageResponse)
async def manual_message(
    conversation_id: str, payload: ManualMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    existing = db.query(SalesConversation).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == current_user.company_id,
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    require_project_access(db, current_user, existing.project_id)
    return await send_manual_message(
        db, conversation_id=conversation_id, company_id=current_user.company_id,
        user_id=current_user.id, content=payload.content.strip(),
    )


@router.post("/drafts/{draft_id}/decision")
def decide_draft(
    draft_id: str,
    payload: DraftDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(TENANT_MANAGER_ROLES)),
):
    draft = db.query(OutboundMessage).join(SalesConversation).filter(
        OutboundMessage.id == draft_id,
        SalesConversation.company_id == current_user.company_id,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="This draft has already been reviewed.")
    # Approval still does not dispatch: providers are deliberately disabled in this delivery.
    draft.status = "approved" if payload.action == "approve" else "rejected"
    draft.approved_by_user_id = current_user.id
    draft.approved_at = datetime.utcnow()
    draft.last_error = payload.reason if payload.action == "reject" else None
    db.commit()
    return {"id": draft.id, "status": draft.status, "dispatch_enabled": False}
