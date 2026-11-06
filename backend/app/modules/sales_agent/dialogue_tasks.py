"""Group 4: deterministic reference resolution and non-destructive task transitions."""
from datetime import datetime, timezone
import hashlib
from .understanding_contract import DialogueState, Task
from .dialogue_store import check_scope
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from .turn_context import choice_index


def task_id(message_id, request_id):
    return hashlib.sha256(f'{message_id}:{request_id}'.encode()).hexdigest()[:40]


def resolve_reference(db, scope, state, reference, *, now=None):
    """Resolve a reference against actual outbound messages, not array order."""
    now = now or datetime.now(timezone.utc)
    conversation = check_scope(db, scope)
    index = choice_index(reference.expression)
    offers = []
    for offer in state.offers:
        if reference.kind != 'ambiguous' and offer.kind != reference.kind:
            continue
        message = scoped_messages_query(db, conversation).filter_by(id=offer.message_id,
            direction='outbound').first()
        if not message or message.status in {'failed', 'cancelled'}:
            continue
        if (message.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
            continue
        offers.append((message.created_at, message.id, offer))
    if index is not None:
        if not offers:
            return None
        newest = max((date, identifier) for date, identifier, _ in offers)
        candidates = [o for date, identifier, o in offers if (date, identifier) == newest]
        if len(candidates) != 1:
            return None
        offer = candidates[0]
        if offer.expires_at and offer.expires_at <= now:
            return None  # Never revive an older offer after expiry.
        if not 0 <= index < len(offer.option_ids):
            return None
        return {'kind': offer.kind, 'id': offer.option_ids[index], 'message_id': offer.message_id}
    if reference.kind == 'property':
        from .commercial_context import build_commercial_context
        from app.modules.projects.models import Project
        context = build_commercial_context(db, project=db.get(Project, scope.project_id),
            company_id=scope.company_id, lead_id=scope.lead_id, channel=conversation.channel)
        matches = [p for p in context['property_types']
                   if p['property_type'].casefold() == reference.expression.strip().casefold()]
        if len(matches) == 1:
            return {'kind':'property', 'id':matches[0]['id'], 'message_id':None}
    if reference.kind == 'appointment' and offers:
        import re
        from zoneinfo import ZoneInfo
        from app.modules.projects.models import Project
        expression=reference.expression.strip().upper()
        if not re.fullmatch(r'\d{1,2}(?::\d{2})?(?:\s*[AP]M)?',expression):
            return None
        parsed=None
        for fmt in ('%I:%M %p','%I %p','%I:%M%p','%I%p','%H:%M'):
            try:
                parsed=datetime.strptime(expression,fmt).time();break
            except ValueError:
                continue
        if parsed is None:return None
        newest=max((date,identifier) for date,identifier,_ in offers)
        matches=[]
        zone=ZoneInfo(db.get(Project,scope.project_id).timezone or 'UTC')
        for date,identifier,offer in offers:
            if (date,identifier)!=newest or (offer.expires_at and offer.expires_at<=now):continue
            for value in offer.option_ids:
                try:
                    instant=datetime.fromisoformat(value)
                    instant=instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant
                    local=instant.astimezone(zone)
                except ValueError:
                    continue
                if instant>now and local.time().replace(tzinfo=None)==parsed:
                    matches.append({'kind':'appointment','id':value,'message_id':identifier})
        if len(matches)==1:return matches[0]
    return None


def prepare_tasks(state, understanding, message_id):
    state = DialogueState.model_validate(state.model_dump())
    # Turn-only restrictions expire, persistent restrictions are never silently removed.
    restrictions = [c for c in state.constraints if c.scope == 'until_explicit_change']
    from .request_safety import explicit_reversal
    for release in understanding.releases:
        if explicit_reversal(release.evidence) and understanding.permits(release.topic,release.subject):
            restrictions = [c for c in restrictions if not (c.topic == release.topic and c.subject == release.subject)]
    for constraint in understanding.constraints:
        if constraint not in restrictions:
            restrictions.append(constraint)
    for request in understanding.requests:
        if request.polarity == 'exclude':
            from .understanding_contract import Constraint
            constraint = Constraint(topic=request.topic, subject=request.subject, scope='turn', evidence=request.evidence)
            if constraint not in restrictions:
                restrictions.append(constraint)
    state.constraints = restrictions
    for preference in understanding.preferences:
        state.preferences = [p for p in state.preferences if p.key != preference.key] + [preference]
    existing = {t.id for t in state.tasks}
    groups = {rid: f'{message_id}:{g.id}' for g in understanding.alternatives for rid in g.request_ids}
    for request in understanding.requests:
        if request.polarity != 'request':
            continue
        identifier = task_id(message_id, request.id)
        if identifier not in existing:
            state.tasks.append(Task(id=identifier, topic=request.topic, subject=request.subject,
                status='awaiting_user' if understanding.requires_clarification else 'pending',
                request_ids=[request.id], source_message_id=message_id, alternative_group=groups.get(request.id)))
    # A fresh explicit request supersedes a previous unresolved copy, not an
    # unrelated task. Its historical state remains in append-only events.
    current = [t for t in state.tasks if t.source_message_id == message_id]
    for task in state.tasks:
        if task.source_message_id != message_id and task.status in {'blocked','awaiting_user','suspended'}:
            if any(n.topic == task.topic and n.subject == task.subject for n in current):
                task.status = 'cancelled'
    state.last_understanding = understanding
    return DialogueState.model_validate(state.model_dump())


def restricted(state, task):
    return any(c.topic == task.topic and (c.subject is None or task.subject is None or c.subject == task.subject)
               for c in state.constraints)


def record_result(state, task, result):
    statuses = {'success':'completed', 'partial':'completed', 'empty':'blocked',
                'denied':'blocked', 'revoked':'blocked', 'conflict':'blocked',
                'error':'suspended', 'uncertain':'awaiting_user'}
    task.status = statuses[result.status]
    if task.topic.value == 'pricing' and result.status == 'partial' and any(
        p.get('starting_price') is None or not p.get('currency') for p in result.data.get('property_types',[])):
        task.status = 'blocked'
    possible_fallback = task.topic.value == 'materials' and result.status == 'partial' and not result.data.get('coverage_confirmed', False)
    if possible_fallback:
        task.status = 'awaiting_user'
    if task.status == 'completed' and task.alternative_group:
        for other in state.tasks:
            if other.id != task.id and other.alternative_group == task.alternative_group and other.status != 'completed':
                other.status = 'cancelled'
    # A lookup is not delivery. The later composer/dispatcher must fulfill this
    # need; do not tell diagnostics that an unsent file reached the lead.
    if task.topic.value == 'materials' and result.status in {'success','partial'} and not possible_fallback:
        task.status = 'pending'
