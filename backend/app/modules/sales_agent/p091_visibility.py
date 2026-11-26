"""P09.1: keep deleted opportunities out of the live Agent surface.

This is an additive visibility/access hotfix. It does NOT remove historical
messages, appointments or audit rows and does not enable P09 hard deletion.

The override GET route must be registered BEFORE the legacy Agent router. The
router-wide dependency is applied when including the legacy Agent router and
prevents direct reads and writes to a deleted conversation by its ID.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.sales_crm.models import Lead
from app.modules.users.models import TENANT_MANAGER_ROLES, User, UserRole
from app.modules.users.project_access import project_ids_for_user

from .models import SalesConversation
from .router import conversations as legacy_conversations
from .schemas import ConversationSummary

router = APIRouter()


def only_active_conversations(db: Session, *, company_id: str, summaries: list[dict]) -> list[dict]:
    """Fail closed for soft-deleted leads, scoped to the authenticated Company.

    No phone-number join is used: one buyer can have multiple opportunities in
    one Company, and identical numbers in another Company remain independent.
    """
    lead_ids = {row.get('lead_id') for row in summaries if row.get('lead_id')}
    if not lead_ids:
        return []
    active_ids = {lead_id for (lead_id,) in db.query(Lead.id).filter(
        Lead.company_id == company_id,
        Lead.id.in_(lead_ids),
        Lead.deleted_at.is_(None),
    ).all()}
    return [row for row in summaries if row.get('lead_id') in active_ids]


def guard_active_conversation(request: Request, db: Session = Depends(get_db)) -> None:
    """Apply to all pre-existing /sales-agent routes as an include dependency.

    In particular: messages, operational-context, Hermes state, pause/resume,
    manual send, failed-turn retry and effect retries cannot access a soft-
    deleted lead even if its conversation UUID is supplied directly.
    """
    conversation_id = request.path_params.get('conversation_id')
    if not conversation_id:
        return
    present = db.query(SalesConversation.id).join(
        Lead, Lead.id == SalesConversation.lead_id,
    ).filter(
        SalesConversation.id == conversation_id,
        SalesConversation.company_id == Lead.company_id,
        Lead.deleted_at.is_(None),
    ).first()
    if not present:
        # The same response for a missing conversation avoids disclosing whether
        # a prior Company/Lead record existed at all.
        raise HTTPException(status_code=404, detail='Conversation not found.')


@router.get('/conversations', response_model=list[ConversationSummary])
def active_conversations(
    response: Response,
    project_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker([*TENANT_MANAGER_ROLES, UserRole.MKT, UserRole.SALES])),
):
    """Preserve existing RBAC, project filtering and message redaction."""
    response.headers['Cache-Control'] = 'no-store'
    summaries = legacy_conversations(project_id=project_id, db=db, current_user=current_user)
    return only_active_conversations(db, company_id=current_user.company_id, summaries=summaries)
