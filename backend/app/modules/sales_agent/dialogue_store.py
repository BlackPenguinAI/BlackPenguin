"""Scoped compare-and-swap persistence, with no commit and no business actions."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .dialogue_models import SalesDialogueState, SalesDialogueEvent
from .understanding_contract import DialogueState
from .models import SalesConversation, SalesConversationLeadContext, SalesMessage
from app.modules.sales_crm.models import Lead
from app.modules.projects.models import ProjectPropertyType, ProjectSalesAsset


class DialogueConflict(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    company_id: str
    project_id: str
    conversation_id: str
    lead_id: str

    def query(self, db, model):
        return db.query(model).filter_by(**self.__dict__)


def check_scope(db, scope):
    conversation = db.query(SalesConversation).filter_by(id=scope.conversation_id,
        company_id=scope.company_id, project_id=scope.project_id, lead_id=scope.lead_id).first()
    lead = db.query(Lead).filter_by(id=scope.lead_id, company_id=scope.company_id,
                                  project_id=scope.project_id, deleted_at=None).first()
    if not conversation or not lead:
        raise PermissionError('Dialogue scope does not match the active opportunity.')
    contexts = db.query(SalesConversationLeadContext).filter_by(conversation_id=conversation.id).all()
    if contexts and not any(c.lead_id == scope.lead_id and c.is_active for c in contexts):
        raise PermissionError('Dialogue opportunity is not active.')
    return conversation


def load(db, scope):
    check_scope(db, scope)
    row = scope.query(db, SalesDialogueState).first()
    if row is None:
        return 0, DialogueState()
    state = DialogueState.model_validate(row.state_json)
    if row.schema_version != state.version:
        raise ValueError('Stored dialogue schema version is unsupported or inconsistent.')
    return row.revision, state


def validate_references(db, scope, state):
    from .conversation_scope import scoped_messages_query
    conversation = check_scope(db, scope)
    if state.selected_property_type_id and not db.query(ProjectPropertyType.id).filter_by(
            id=state.selected_property_type_id, project_id=scope.project_id).first():
        raise PermissionError('Selected property is outside this Project.')
    for offer in state.offers:
        message = scoped_messages_query(db, conversation).filter_by(id=offer.message_id,
            direction='outbound').first()
        if not message or (message.metadata_json or {}).get('lead_id', scope.lead_id) != scope.lead_id:
            raise PermissionError('Offer belongs to another opportunity.')
        if offer.kind == 'property':
            count = db.query(ProjectPropertyType.id).filter(ProjectPropertyType.id.in_(set(offer.option_ids)), ProjectPropertyType.project_id == scope.project_id).count()
            if count != len(set(offer.option_ids)):
                raise PermissionError('Offer has foreign property identifiers.')
        if offer.kind == 'material':
            count = db.query(ProjectSalesAsset.id).filter(ProjectSalesAsset.id.in_(set(offer.option_ids)), ProjectSalesAsset.company_id == scope.company_id, ProjectSalesAsset.project_id == scope.project_id).count()
            if count != len(set(offer.option_ids)):
                raise PermissionError('Offer has foreign material identifiers.')


def validate_write_request(event_key, expected_revision, kind):
    if not isinstance(event_key, str) or not 1 <= len(event_key) <= 120:
        raise ValueError('An event key of 1–120 characters is required.')
    if kind not in {'state_update', 'understanding_preview'}:
        raise ValueError('Unsupported dialogue event kind.')
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError('A non-negative expected revision is required.')


def save(db, scope, *, event_key, expected_revision, state, kind='state_update', metadata=None):
    validate_write_request(event_key, expected_revision, kind)
    check_scope(db, scope)
    state = DialogueState.model_validate(state.model_dump() if isinstance(state, DialogueState) else state)
    # No credentials should enter this store. Defense-in-depth also redacts
    # diagnostic metadata before persistence; state evidence remains verbatim.
    from .monitor import redact
    payload = {'kind': kind, 'expected_revision': expected_revision,
               'state': state.model_dump(mode='json'), 'metadata': redact(metadata or {})}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 256000:
        raise ValueError('Dialogue event exceeds the 256 KB limit.')
    validate_references(db, scope, state)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    prior = scope.query(db, SalesDialogueEvent).filter_by(event_key=event_key).first()
    if prior:
        if prior.payload_hash != digest:
            raise DialogueConflict('Event key already used for different content.')
        return prior.revision, DialogueState.model_validate(prior.state_after)
    try:
        # Python's legacy sqlite transaction mode does not BEGIN for SELECT.
        # A first SAVEPOINT would otherwise commit on RELEASE, escaping the
        # caller's rollback. PostgreSQL already has a real transaction here.
        connection = db.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN')
        with db.begin_nested():
            row = scope.query(db, SalesDialogueState).with_for_update().first()
            if row is None:
                if expected_revision != 0:
                    raise DialogueConflict('Dialogue revision changed.')
                row = SalesDialogueState(**scope.__dict__, revision=0, state_json=DialogueState().model_dump(mode='json'))
                db.add(row); db.flush()
            if row.revision != expected_revision:
                raise DialogueConflict('Dialogue revision changed.')
            stored = DialogueState.model_validate(row.state_json)
            if row.schema_version != stored.version:
                raise ValueError('Stored dialogue schema version is unsupported or inconsistent.')
            new_revision = expected_revision + 1
            changed = db.execute(update(SalesDialogueState).where(
                SalesDialogueState.id == row.id, SalesDialogueState.revision == expected_revision
            ).values(revision=new_revision, schema_version=state.version,
                     state_json=state.model_dump(mode='json'), updated_at=datetime.now(timezone.utc)),
                execution_options={'synchronize_session': False}).rowcount
            if changed != 1:
                raise DialogueConflict('Dialogue revision changed.')
            db.add(SalesDialogueEvent(**scope.__dict__, event_key=event_key, revision=new_revision,
                kind=kind, payload_hash=digest, payload_json=payload, state_after=state.model_dump(mode='json')))
            db.flush(); db.expire(row)
        return new_revision, state
    except IntegrityError as exc:
        raise DialogueConflict('Concurrent dialogue update; reload and retry the same event key.') from exc
