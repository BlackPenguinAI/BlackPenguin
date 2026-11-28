"""Pure P04 verification rules. No LangGraph interpretation or API requests."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re


def booking_fingerprint(row) -> str:
    """Detect any change to the booked visit before cancellation/rescheduling."""
    value = {
        'id': str(row.id), 'lead_id': str(row.lead_id),
        'project_id': str(row.project_id), 'assigned_sales_user_id': row.assigned_sales_user_id,
        'meeting_time': row.meeting_time.isoformat(), 'duration_minutes': row.duration_minutes,
        'status': row.status.value if hasattr(row.status, 'value') else str(row.status),
        'visit_unit_id': row.visit_unit_id, 'visit_property_type_id': row.visit_property_type_id,
        'visit_address': row.visit_address, 'visit_context': row.visit_context,
    }
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _property_visible(reply, record):
    # display_name is attached only by the scoped live domain renderer, not
    # taken from an SDK tool argument. Keep the internal reference for all
    # operation/offer identity checks. Legacy records use their reference.
    ref = record.get('unit_id')
    if not isinstance(ref,str) or not ref.strip():
        return False
    label = record.get('display_name')
    if label is None:
        return ref.casefold() in reply.casefold()
    if not isinstance(label, str) or not label.strip():
        return False
    return bool(re.search(r'(?<![\w-])' + re.escape(label) + r'(?![\w-])', reply, re.I))


def recap_visible(reply: str, request: dict) -> bool:
    """Fail-closed: prove the delivered text included exact house/date/hour.

    The proof is deliberately strict, because a model tool-result is not a
    customer-visible confirmation question. Exact ISO date, HH:MM and property
    reference must be present along with an explicit confirmation question.
    """
    if not isinstance(reply,str) or len(reply)>4000:
        return False
    if request.get('live_change_version'):
        from .live_changes import recap_matches
        return recap_matches(reply,request)
    required=[request.get('date'),request.get('start_time')]
    if not _property_visible(reply,request) or not all(isinstance(x,str) and x and x.casefold() in reply.casefold() for x in required):
        return False
    if not re.search(r'\b(?:confirm|book|replace|reschedule)\b',reply,re.I) or '?' not in reply:
        return False
    return True


def evidence_live_inbound(db, scope, inbound_message_id: str, *, after_reply_message_id: str | None = None):
    """Authenticated persisted inbound, distinct and after the customer recap."""
    from app.modules.sales_agent.models import SalesMessage
    inbound = db.query(SalesMessage).filter_by(
        id=inbound_message_id, conversation_id=scope.conversation_id,
        direction='inbound', role='user',
    ).one_or_none()
    if not inbound or (inbound.metadata_json or {}).get('lead_id',scope.lead_id)!=scope.lead_id:
        raise PermissionError('The operation must be grounded in this lead inbound message')
    if after_reply_message_id:
        recap=db.query(SalesMessage).filter_by(
            id=after_reply_message_id, conversation_id=scope.conversation_id,
            direction='outbound', role='assistant',
        ).one_or_none()
        if not recap or recap.status not in {'sent','delivered','accepted','read'} or (
            recap.metadata_json or {}).get('lead_id',scope.lead_id)!=scope.lead_id:
            raise PermissionError('A delivered same-lead confirmation recap is required')
        if (inbound.created_at, inbound.id) <= (recap.created_at, recap.id):
            raise PermissionError('Confirmation cannot precede the delivered recap')
    return inbound


def visible_menu(reply: str, menu: dict) -> bool:
    """Every numbered line must have the exact server-produced option label."""
    opts = menu.get('options') or []
    minimum = 1 if menu.get('type') in {'visit_day','visit_time'} and menu.get('display_name') else 2
    if not minimum <= len(opts) <= 10:
        return False
    lines = {}
    for line in reply.splitlines():
        match = re.fullmatch(r'\s*([1-9])\s*[.)]\s+(.+?)\s*',line)
        if match:
            lines[int(match[1])] = match[2].strip().casefold()
    if not all(x.get('index') in lines and x.get('label','').casefold() in lines[x['index']]
               for x in opts):
        return False
    if menu['type']=='visit_time':
        # The day and property must be visible, not just a list of anonymous hours.
        if not _property_visible(reply,menu):
            return False
        day = menu.get('date')
        if not day:
            return False
        from .contextual_choices import _date_label
        if day not in reply and _date_label(day).casefold() not in reply.casefold():
            return False
    elif menu['type']=='visit_day' and not _property_visible(reply,menu):
        return False
    return True
