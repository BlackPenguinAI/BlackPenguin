from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole

from .models import AgentRun, OutboundMessage, SalesConversation
from .schemas import AgentRunResponse, ConversationSummary, DraftDecision, SimulationRequest
from .service import simulate_turn


router = APIRouter()


@router.post("/simulate", response_model=AgentRunResponse)
async def simulate(
    payload: SimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES])),
):
    return await simulate_turn(
        db,
        company_id=current_user.company_id,
        lead_id=payload.lead_id,
        inbound_text=payload.message,
        event_id=payload.event_id,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    query = db.query(SalesConversation).filter(SalesConversation.company_id == current_user.company_id)
    if current_user.role == UserRole.SALES:
        from app.modules.sales_crm.models import Lead
        query = query.join(Lead, Lead.id == SalesConversation.lead_id).filter(Lead.assigned_sales_user_id == current_user.id)
    return query.order_by(SalesConversation.updated_at.desc()).all()


@router.post("/drafts/{draft_id}/decision")
def decide_draft(
    draft_id: str,
    payload: DraftDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.SALES])),
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
