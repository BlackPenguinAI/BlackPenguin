"""Staff-only global Hermes settings and scoped read-only diagnostics.

Mounted below /api/v1/ai/hermes; no route invokes the Hermes runtime or
performs a sales operation. Legacy conversation dispatch remains unchanged.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session
from app.db.postgres import get_db
from app.modules.auth.deps import RoleChecker
from app.modules.users.models import User, UserRole
from . import staff_config as control

staff_only = RoleChecker([UserRole.SUPERADMIN])
router = APIRouter(prefix='/hermes', tags=['Hermes Staff Control'])


def no_cache(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    configuration: control.HermesGlobalPolicy
    change_note: str = Field(default='', max_length=500)


@router.get('/global', dependencies=[Depends(no_cache)])
def global_config(db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    return control.snapshot(db)


@router.get('/versions', dependencies=[Depends(no_cache)])
def list_versions(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                  db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    return {**control.versions(db, offset=(page - 1) * page_size, limit=page_size),
            'page': page, 'page_size': page_size}


@router.get('/versions/{version_id}', dependencies=[Depends(no_cache)])
def version_detail(version_id: str, db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    try:
        return control.serialize_version(control.find_version(db, version_id), include_config=True)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/drafts', status_code=201, dependencies=[Depends(no_cache)])
def create_draft(payload: DraftRequest, db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    return control.create_draft(db, configuration=payload.configuration.model_dump(),
                                note=payload.change_note, actor_id=actor.id)


@router.post('/versions/{version_id}/publish', dependencies=[Depends(no_cache)])
def publish(version_id: str, db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    try:
        return control.publish(db, version_id=version_id, actor_id=actor.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.post('/versions/{version_id}/restore', dependencies=[Depends(no_cache)])
def restore(version_id: str, db: Session = Depends(get_db), actor: User = Depends(staff_only)):
    try:
        return control.restore(db, version_id=version_id, actor_id=actor.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc


@router.get('/staff/conversations/{conversation_id}/context', dependencies=[Depends(no_cache)])
def staff_context(conversation_id: str, company_id: str = Query(min_length=1),
                  project_id: str = Query(min_length=1), lead_id: str = Query(min_length=1),
                  request: Request = None, db: Session = Depends(get_db),
                  actor: User = Depends(staff_only)):
    from .bp_models import HermesSalesState, HermesSalesStateEvent
    from .bp_operation_models import HermesSalesOperation
    from app.modules.sales_agent.monitor import selected, audit
    selected(db, company_id, project_id, lead_id, conversation_id)
    scope = dict(company_id=company_id, project_id=project_id, lead_id=lead_id, conversation_id=conversation_id)
    row = db.query(HermesSalesState).filter_by(**scope).one_or_none()
    events = db.query(HermesSalesStateEvent).filter_by(**scope).order_by(
        HermesSalesStateEvent.revision.desc()).limit(12).all()
    operations = db.query(HermesSalesOperation).filter_by(**scope).order_by(
        HermesSalesOperation.created_at.desc()).limit(12).all()
    state = row.state_json if row and isinstance(row.state_json, dict) else {}
    # No raw conversation, contacts, tool arguments, PII or bearer URLs here.
    safe = {
        'phase': state.get('conversation_phase'),
        'focus': state.get('conversation_focus'),
        'primary_preferences': state.get('search_preferences'),
        'temporary_filters': state.get('property_filters'),
        'visit_draft': {k: v for k, v in (state.get('visit_draft') or {}).items()
                        if k in {'status', 'unit_id', 'property_type_id', 'project_id', 'date', 'start_time', 'timezone'}},
        'last_presented_units': state.get('last_presented_units'),
        'choice_set': {'kind': (state.get('last_presented_choice_set') or {}).get('kind'),
                       'count': len((state.get('last_presented_choice_set') or {}).get('options') or [])},
    }
    audit(db, actor, request, company_id, 'hermes_context_view', conversation_id,
          {'project_id': project_id, 'lead_id': lead_id, 'state_revision': row.revision if row else None})
    return {'has_state': bool(row), 'revision': row.revision if row else 0,
            'engine_version': row.engine_version if row else None,
            'state': safe if row else None,
            'recent_events': [{'revision': e.revision, 'kind': e.event_type,
                               'at': e.recorded_at} for e in events],
            'operations': [{'type': e.operation_type, 'status': e.status,
                            'at': e.created_at} for e in operations],
            'read_only': True, 'live_routing_enabled': False}

# Tenant read-only projection; the same project access checks used by the
# existing Agent/Schedule operational-context endpoints are mandatory.
tenant_reader = RoleChecker([UserRole.ADMIN, UserRole.ASSISTANT, UserRole.MKT, UserRole.SALES])


def _tenant_projection(db: Session, conversation):
    from .conversation_inspector import inspect_conversation
    view = inspect_conversation(db, conversation)
    # Preserve the old P06 envelope for older UI clients, but never raw state.
    view['state'] = {'phase':view['phase'], 'focus':view['focus'],
                     'primary_preferences':view['primary_preferences'],
                     'temporary_filters':view['property_filters'], 'visit_draft':view['visit_draft'],
                     'last_presented_units':[p['reference'] for p in view['presented_properties']]} if view['has_state'] else None
    return view


@router.get('/conversations/{conversation_id}/context', dependencies=[Depends(no_cache)])
def tenant_context(conversation_id: str, db: Session = Depends(get_db),
                   actor: User = Depends(tenant_reader)):
    from app.modules.sales_agent.operational_context import scoped_conversation
    conversation = scoped_conversation(db, actor, conversation_id)
    return _tenant_projection(db, conversation)


@router.get('/meetings/{meeting_id}/context', dependencies=[Depends(no_cache)])
def tenant_meeting_context(meeting_id: str, db: Session = Depends(get_db),
                           actor: User = Depends(tenant_reader)):
    from app.modules.sales_agent.operational_context import meeting_context
    from app.modules.sales_crm.models import Meeting
    from app.modules.sales_agent.models import SalesConversation
    # Existing policy handles project access and Sales ownership.
    permitted = meeting_context(db, actor, meeting_id)
    if permitted.get('scope_limited'):
        return {'has_state': False, 'read_only': True, 'scope_limited': True,
                'reason': 'Only the selected appointment is accessible.'}
    meeting = db.get(Meeting, meeting_id)
    conversations = db.query(SalesConversation).filter_by(
        company_id=actor.company_id, project_id=meeting.project_id,
        lead_id=meeting.lead_id).limit(2).all()
    if len(conversations) != 1:
        return {'has_state': False, 'read_only': True, 'live_routing_enabled': False,
                'reason': 'Multiple or no conversations; select a specific conversation to view Hermes context.'}
    from app.modules.sales_agent.operational_context import scoped_conversation
    return _tenant_projection(db, scoped_conversation(db, actor, conversations[0].id))
