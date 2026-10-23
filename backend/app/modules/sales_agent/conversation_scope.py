"""Safe message scoping for a physical provider thread.

One SMS/WhatsApp sender-recipient pair can be reused when the same contact
becomes a Lead for another Project.  The provider thread stays physical, but
the AI and the operations UI must only see the currently active opportunity.
"""

from __future__ import annotations

from sqlalchemy.orm import Query, Session

from .models import SalesConversation, SalesConversationLeadContext, SalesMessage


def scoped_messages_query(
    db: Session,
    conversation: SalesConversation,
    *,
    lead_id: str | None = None,
) -> Query:
    """Return messages belonging to the active activation of ``lead_id``.

    Legacy conversations without context rows keep their complete history.
    Once a physical thread has opportunity contexts, ``activated_at`` becomes
    the hard lower boundary. Re-activating an earlier Lead intentionally starts
    a fresh context instead of replaying a previous Project conversation.
    """

    target_lead_id = lead_id or conversation.lead_id
    base = db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation.id,
    )
    context = db.query(SalesConversationLeadContext).filter(
        SalesConversationLeadContext.conversation_id == conversation.id,
        SalesConversationLeadContext.lead_id == target_lead_id,
        SalesConversationLeadContext.is_active.is_(True),
    ).first()
    if context:
        return base.filter(SalesMessage.created_at >= context.activated_at)

    # A context-aware thread with no matching active context is inconsistent.
    # Fail closed so another opportunity is never exposed to the model or UI.
    has_context = db.query(SalesConversationLeadContext.id).filter(
        SalesConversationLeadContext.conversation_id == conversation.id,
    ).first()
    return base.filter(False) if has_context else base

