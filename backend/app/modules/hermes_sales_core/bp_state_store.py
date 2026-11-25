"""P03 scoped Hermes conversation state, persisted in BlackPenguin PostgreSQL.

All writes are explicit. No commit, HTTP send, messaging or booking occurs here.
The caller is responsible for COMMIT/ROLLBACK on the surrounding SQLAlchemy
transaction. Duplicate event keys are idempotent ONLY for identical payloads.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .contracts import TurnScope
from . import sales_preferences, property_filters
from .bp_context import require_scoped_entities
from .bp_models import HermesSalesState, HermesSalesStateEvent

VERSION = 'hermes-sales-state/1.0'
ENGINE = 'hermes-sales-core/0.2-p02'
MAX_STATE_BYTES = 256_000
SENSITIVE_KEYS = frozenset({
    'api_key', 'auth_token', 'secret', 'password', 'authorization', 'client_secret',
    'openrouter_api_key', 'access_token', 'refresh_token', 'db_url', 'database_url',
})
ALLOWED_STATE_KEYS = frozenset({
    'lead', 'conversation_focus', 'search_preferences', 'search_preferences_history',
    'property_filters', 'property_filters_history', 'active_search',
    'search_sessions', 'last_presented_choice_set', 'choice_set_initialized',
    'last_presented_units', 'shortlisted_unit_ids', 'property_interests',
    'visit_draft', 'last_slot_search', 'booking_proposal', 'confirmation_request',
    'shared_media', 'offered_assets', 'conversation_phase', 'answered_topics',
    'conversation_transitions', 'last_assistant_reply', 'visit_planning_paused',
})


class HermesStateConflict(ValueError):
    pass


@dataclass(frozen=True)
class LoadedState:
    revision: int
    data: dict
    schema_version: str = VERSION


def blank_state(scope: TurnScope) -> dict:
    """New conversations start clean; no LangGraph or demo-state conversion."""
    return {
        'lead': {},
        'conversation_focus': {'project_id': scope.project_id, 'unit_id': None,
                               'property_type_id': None, 'ambiguous': False},
        'search_preferences': sales_preferences.empty(),
        'search_preferences_history': [],
        'property_filters': property_filters.empty(),
        'property_filters_history': [],
        'active_search': None,
        'search_sessions': [],
        'last_presented_choice_set': None,
        'choice_set_initialized': True,
        'last_presented_units': [],
        'shortlisted_unit_ids': [],
        'property_interests': [],
        'visit_draft': {'unit_id': None, 'date': None, 'start_time': None, 'status': 'idle'},
        'last_slot_search': None, 'booking_proposal': None,
        'confirmation_request': None, 'shared_media': {}, 'offered_assets': {},
        'conversation_phase': 'discovery', 'answered_topics': [],
        'conversation_transitions': [], 'last_assistant_reply': None,
        'visit_planning_paused': False,
    }


def _forbidden_key(value, *, depth=0):
    if depth > 30:
        raise ValueError('Hermes state nesting is too deep')
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError('Hermes state keys must be strings')
            if key.casefold() in SENSITIVE_KEYS:
                raise ValueError('Secrets are forbidden in Hermes conversation state')
            _forbidden_key(child, depth=depth+1)
    elif isinstance(value, list):
        for child in value:
            _forbidden_key(child, depth=depth+1)


def _normalized(scope: TurnScope, state: dict) -> tuple[dict, str]:
    if not isinstance(state, dict) or set(state) - ALLOWED_STATE_KEYS:
        raise ValueError('Unknown Hermes state fields')
    payload = blank_state(scope)
    payload.update(deepcopy(state))
    if payload['conversation_focus'].get('project_id') != scope.project_id:
        raise PermissionError('Hermes focus refers to a different project')
    _forbidden_key(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_STATE_BYTES:
        raise ValueError('Hermes state exceeds 256 KB')
    return json.loads(encoded), sha256(encoded.encode('utf-8')).hexdigest()


def _validate_references(db, scope: TurnScope, state: dict) -> None:
    """Only published/same-project IDs may be placed in durable Hermes state."""
    from app.modules.projects.models import ProjectUnit, ProjectPropertyType
    from app.modules.sales_agent.models import SalesMessage

    unit_rows = db.query(ProjectUnit).filter(ProjectUnit.project_id == scope.project_id).all()
    approved_type_rows = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == scope.project_id,
        ProjectPropertyType.review_status == 'confirmed',
    ).all()
    units = {str(u.id) for u in unit_rows} | {str(u.unit_code) for u in unit_rows}
    types = {str(p.id) for p in approved_type_rows}

    focus = state['conversation_focus']
    if focus.get('unit_id') and str(focus['unit_id']) not in units:
        raise PermissionError('Hermes focus unit is outside the approved project inventory')
    if focus.get('property_type_id') and str(focus['property_type_id']) not in types:
        raise PermissionError('Hermes focus type is outside the approved project catalog')
    for key in ('last_presented_units', 'shortlisted_unit_ids'):
        refs = state.get(key) or []
        if not isinstance(refs, list) or any(not isinstance(x, str) or x not in units | types for x in refs):
            raise PermissionError('Hermes selection contains a foreign or unknown property')
    draft = state.get('visit_draft') or {}
    if draft.get('unit_id') and str(draft['unit_id']) not in units:
        raise PermissionError('Hermes draft visit references another inventory')
    menu = state.get('last_presented_choice_set')
    if menu:
        if not isinstance(menu, dict) or menu.get('type') not in ('property', 'media', 'visit_day', 'visit_time'):
            raise ValueError('Invalid Hermes choice menu')
        source_id = menu.get('source_reply_message_id')
        if not source_id:
            raise PermissionError('A choice menu requires a delivered outbound message ID')
        source = db.query(SalesMessage).filter(
            SalesMessage.id == source_id, SalesMessage.conversation_id == scope.conversation_id,
            SalesMessage.direction == 'outbound',
        ).one_or_none()
        if (source is None or (source.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id
                or source.status not in {'sent', 'delivered', 'accepted'}):
            raise PermissionError('Hermes menu is not tied to a valid outbound message')
        opts = menu.get('options') or []
        if not isinstance(opts, list) or not 2 <= len(opts) <= 10:
            raise ValueError('Hermes menu options are invalid')
        # The model's hidden tool results are not a buyer-visible menu. Read
        # the ACTUAL outbound text and prove every displayed option existed.
        visible = {}
        for line in str(source.content or '').splitlines():
            match = re.match(r'^\s*([1-9])\s*[.)]\s+(.+?)\s*$', line)
            if match:
                visible[int(match.group(1))] = match.group(2).casefold()
        seen_refs = set()
        for index, item in enumerate(opts, 1):
            if not isinstance(item, dict) or item.get('index') != index:
                raise ValueError('Hermes menu numbering must be exact and ordered')
            if index not in visible:
                raise PermissionError('Hermes menu was not numbered in the delivered reply')
            if menu['type'] == 'property':
                ref = str(item.get('unit_id') or '')
                if ref not in units | types:
                    raise PermissionError('Hermes menu refers to foreign property')
                if ref in seen_refs:
                    raise ValueError('Hermes property menu cannot repeat a property reference')
                seen_refs.add(ref)
                label = str(item.get('label') or '').strip().casefold()
                if ref.casefold() not in visible[index] and (not label or label not in visible[index]):
                    raise PermissionError('Hermes menu property was not visible in the delivered reply')


def load(db, scope: TurnScope) -> LoadedState:
    require_scoped_entities(db, scope)
    row = db.query(HermesSalesState).filter_by(**scope.__dict__).one_or_none()
    if row is None:
        return LoadedState(0, blank_state(scope))
    if row.schema_version != VERSION:
        raise HermesStateConflict('Hermes state schema version is unsupported')
    return LoadedState(row.revision, deepcopy(row.state_json))


def save(db, scope: TurnScope, *, expected_revision: int, event_key: str,
         state: dict, event_type: str = 'state_update') -> LoadedState:
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError('Expected revision must be a nonnegative integer')
    if not isinstance(event_key, str) or not 1 <= len(event_key) <= 120:
        raise ValueError('Event key must contain 1–120 characters')
    if event_type not in {'state_update', 'outbound_choice_receipt', 'simulation_receipt'}:
        raise ValueError('Unsupported Hermes state event type')
    require_scoped_entities(db, scope)
    data, digest = _normalized(scope, state)
    _validate_references(db, scope, data)
    existing = db.query(HermesSalesStateEvent).filter_by(
        conversation_id=scope.conversation_id, lead_id=scope.lead_id, event_key=event_key,
    ).one_or_none()
    if existing:
        if existing.payload_hash != digest or existing.event_type != event_type:
            raise HermesStateConflict('Idempotency key reused with a different Hermes state')
        return LoadedState(existing.revision, deepcopy(existing.state_after))
    try:
        # PG row lock prevents two writers from committing the same revision.
        # The nested transaction isolates uniqueness failures from other work.
        connection = db.connection()
        if (connection.dialect.name == 'sqlite'
                and not connection.connection.driver_connection.in_transaction):
            connection.exec_driver_sql('BEGIN')
        with db.begin_nested():
            row = db.query(HermesSalesState).filter_by(**scope.__dict__).with_for_update().one_or_none()
            if row is None:
                if expected_revision != 0:
                    raise HermesStateConflict('Hermes state revision changed')
                row = HermesSalesState(**scope.__dict__, schema_version=VERSION,
                                       engine_version=ENGINE, revision=0,
                                       state_json=blank_state(scope))
                db.add(row)
                db.flush()
            if row.revision != expected_revision:
                raise HermesStateConflict('Hermes state revision changed')
            updated = db.execute(update(HermesSalesState).where(
                HermesSalesState.id == row.id,
                HermesSalesState.revision == expected_revision,
            ).values(revision=expected_revision + 1, schema_version=VERSION,
                     engine_version=ENGINE, state_json=data,
                     updated_at=datetime.now(timezone.utc)),
                     execution_options={'synchronize_session': False}).rowcount
            if updated != 1:
                raise HermesStateConflict('Hermes state compare-and-swap rejected concurrent update')
            db.add(HermesSalesStateEvent(
                **scope.__dict__, event_key=event_key, event_type=event_type,
                revision=expected_revision + 1, schema_version=VERSION,
                payload_hash=digest, state_after=data,
            ))
            db.flush()
            db.expire(row)
        return LoadedState(expected_revision + 1, deepcopy(data))
    except IntegrityError as exc:
        raise HermesStateConflict('Concurrent Hermes state initialization or write; reload and retry') from exc
