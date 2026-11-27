"""HEI-07A: explicit, bounded production PILOT. No GLOBAL mode in this release.

No data or conversation interpretation here. The operator declares exact test
opportunities; the normal staff selector and existing business authorization
still apply. Scope bindings are process-local and never accepted from HTTP.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import os
import re
import time
from typing import Mapping
from uuid import UUID

FIELDS = ('company_id', 'project_id', 'lead_id', 'conversation_id')
READY_URL = 'http://bp-hermes:8080/internal/readiness'
_MAX_SCOPES = 5
_bound = ContextVar('hermes_pilot_scope', default=None)
_admin = ContextVar('hermes_admin_selection', default=False)
# Cache only an authenticated local HTTP readiness result; never a routing decision.
_health_cache = (None, 0.0, False)


@dataclass(frozen=True)
class Pilot:
    revision: str
    scopes: frozenset[tuple[str, ...]]
    phones: tuple[tuple[tuple[str, ...], str], ...]
    expires: datetime
    fingerprint: str


def requested() -> bool:
    return (os.getenv('ENVIRONMENT') == 'production' and
            os.getenv('HERMES_RELEASE_MODE') == 'pilot')


def scope_key(scope: Mapping | object) -> tuple[str, ...]:
    values = tuple(scope.get(k) if isinstance(scope, Mapping) else getattr(scope, k, getattr(scope, 'id', None) if k == 'conversation_id' else None) for k in FIELDS)
    if not all(isinstance(v, str) and str(UUID(v)) == v for v in values):
        raise ValueError('Exact canonical UUID scope required.')
    return values


def configuration() -> Pilot | None:
    """Parse the immutable per-release configuration; expiration is checked separately."""
    if not requested():
        return None
    try:
        revision = os.environ['APP_COMMIT_SHA']
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            return None
        if os.environ['HERMES_RELEASE_SHA'] != revision:
            return None
        if os.getenv('HERMES_RUNTIME_ROLE') not in {'api', 'sdk'}:
            return None
        token = os.environ['HERMES_INTERNAL_TOKEN']
        if not re.fullmatch(r'[0-9a-f]{64}', token):
            return None
        raw = json.loads(os.environ['HERMES_PILOT_SCOPES'])
        if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_SCOPES:
            return None
        if any(not isinstance(item, dict) or set(item) != set(FIELDS) | {'test_phone'} for item in raw):
            return None
        scopes = frozenset(scope_key(item) for item in raw)
        if len(scopes) != len(raw) or any(not isinstance(item['test_phone'], str) or not re.fullmatch(r'\+[1-9][0-9]{7,14}', item['test_phone']) for item in raw):
            return None
        phones = tuple(sorted((scope_key(item), item['test_phone']) for item in raw))
        stamp = os.environ['HERMES_PILOT_UNTIL']
        expires = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        if expires > datetime.now(timezone.utc) + timedelta(days=7):
            return None
        canonical = json.dumps([revision, phones, stamp], separators=(',', ':'))
        return Pilot(revision, scopes, phones, expires, sha256(canonical.encode()).hexdigest())
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def allowed(scope: Mapping | object, config: Pilot | None = None) -> bool:
    config = config if config is not None else configuration()
    try:
        return config is not None and scope_key(scope) in config.scopes
    except (ValueError, TypeError, AttributeError):
        return False


def active(config: Pilot | None) -> bool:
    return config is not None and datetime.now(timezone.utc) < config.expires


def local_sdk_ready(config: Pilot | None) -> bool:
    if not active(config) or os.getenv('HERMES_RUNTIME_ROLE') != 'sdk':
        return False
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    return bool(key and key not in {'test-only', 'disabled', 'offline'})


def sdk_readiness() -> dict:
    """Authenticated private transport/DB/import preflight, not model/provider acceptance."""
    config = configuration()
    if not local_sdk_ready(config):
        raise RuntimeError('SDK pilot configuration is not ready.')
    from run_agent import AIAgent  # noqa: F401
    from sqlalchemy import text
    from app.db.postgres import SessionLocal
    import app.db.base  # noqa: F401
    from sqlalchemy.orm import configure_mappers
    from .staff_models import HermesGlobalSettings
    configure_mappers()
    db = SessionLocal()
    try:
        db.execute(text('SELECT 1'))
        db.query(HermesGlobalSettings.id).limit(1).all()
    finally:
        db.close()
    return {'status': 'ready', 'release': config.revision, 'scope_fingerprint': config.fingerprint,
            'mode': 'pilot', 'transport': 'private-sdk'}


def ready() -> bool:
    """Gate closed by default. API verifies exact authenticated SDK identity."""
    global _health_cache
    config = configuration()
    if not active(config):
        return False
    if os.getenv('HERMES_RUNTIME_ROLE') == 'sdk':
        return local_sdk_ready(config)
    token = os.environ['HERMES_INTERNAL_TOKEN']
    cache_key = (config.fingerprint, sha256(token.encode()).digest())
    now = time.monotonic()
    if _health_cache[0] == cache_key and now - _health_cache[1] < 2:
        return _health_cache[2]
    result = False
    try:
        import httpx
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0), follow_redirects=False, trust_env=False) as client:
            reply = client.get(READY_URL, headers={'Authorization': 'Bearer ' + token})
            result = reply.status_code == 200 and reply.json() == {
                'status': 'ready', 'release': config.revision, 'scope_fingerprint': config.fingerprint,
                'mode': 'pilot', 'transport': 'private-sdk'}
    except Exception:
        result = False  # fail closed; no provider credentials or errors in UI
    _health_cache = (cache_key, time.monotonic(), result)
    return result


def require_execution() -> None:
    """Called at existing preparation, operation, scheduling and dispatcher gates."""
    from .engine_selection import EngineUnavailable
    config = configuration()
    if not active(config):
        raise EngineUnavailable('Hermes pilot is disabled, invalid or expired.')
    if _admin.get() and os.getenv('HERMES_RUNTIME_ROLE') == 'api' and _bound.get() is None:
        return
    if _bound.get() not in config.scopes:
        raise EngineUnavailable('No authorized Hermes pilot execution scope.')


@contextmanager
def bind_scope(scope):
    """An exact persisted scope, never a caller-supplied freeform payload."""
    if not requested():
        yield
        return
    from .engine_selection import EngineUnavailable
    config = configuration()
    if not active(config) or not allowed(scope, config):
        raise EngineUnavailable('Hermes pilot opportunity is not authorized.')
    key = scope_key(scope)
    previous = _bound.get()
    if previous is not None and previous != key:
        raise EngineUnavailable('Hermes execution scope changed.')
    marker = _bound.set(key)
    try:
        yield
    finally:
        _bound.reset(marker)


def assert_bound_scope(scope):
    """Reject scope substitution when existing event contracts are revalidated."""
    if requested() and _bound.get() is not None:
        from .engine_selection import EngineUnavailable
        if not allowed(scope) or scope_key(scope) != _bound.get():
            raise EngineUnavailable('Hermes execution scope changed.')


@contextmanager
def admin_selection():
    """Used only inside the existing SUPERADMIN selection endpoint."""
    marker = _admin.set(True)
    try:
        yield
    finally:
        _admin.reset(marker)


def status_fields() -> dict:
    config = configuration()
    return {'hermes_release_mode': 'pilot' if requested() else 'closed',
            'hermes_pilot_scope_count': len(config.scopes) if config else 0,
            'hermes_pilot_until': config.expires.isoformat() if config else None,
            'hermes_global_certified': False}


def authorize_sdk_job(db, job_id, run_id):
    """Obtain scope independently from the claimed job and its reserved run."""
    from app.modules.sales_agent.models import SalesInboundJob, SalesConversation, AgentRun
    from .engine_selection import EngineUnavailable
    job = db.get(SalesInboundJob, job_id)
    run = db.get(AgentRun, run_id)
    if (not job or job.status != 'processing' or not run or run.status != 'running'
            or run.mode != 'live' or run.conversation_id != job.conversation_id):
        raise EngineUnavailable('SDK request does not identify a claimed reserved run.')
    conversation = db.get(SalesConversation, job.conversation_id)
    if not conversation or not allowed(conversation):
        raise EngineUnavailable('SDK request scope is not authorized.')
    validate_target(db, conversation)
    return {name: getattr(conversation, name) if name != 'conversation_id' else conversation.id for name in FIELDS}


def is_bound() -> bool:
    return requested() and _bound.get() is not None

def _digits(value):
    return re.sub(r'[^0-9]', '', value or '')

def validate_target(db, conversation):
    """Revalidate the real persisted test lead and Telnyx route at effect boundaries."""
    from .engine_selection import EngineUnavailable
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.provider_routes import parts
    config = configuration()
    if not active(config) or not allowed(conversation, config):
        raise EngineUnavailable('Pilot scope unavailable.')
    assert_bound_scope(conversation)
    expected = dict(config.phones)[scope_key(conversation)]
    lead = db.query(Lead).filter_by(id=conversation.lead_id).populate_existing().one_or_none()
    route = parts(conversation)
    if (not lead or not lead.is_test or lead.is_demo or lead.deleted_at
            or lead.company_id != conversation.company_id or lead.project_id != conversation.project_id
            or _digits(lead.phone) != _digits(expected) or not route
            or _digits(route[1]) != _digits(expected)):
        raise EngineUnavailable('Pilot test lead or destination changed.')
    return lead

def validate_deployment_targets():
    """Read-only production preflight; no messages or business writes."""
    from app.db.postgres import SessionLocal
    import app.db.base  # noqa: F401
    from app.modules.sales_agent.models import SalesConversation
    from app.modules.sales_agent.provider_routes import assert_dispatchable
    from .contracts import TurnScope
    from .bp_context import require_scoped_entities
    from app.modules.onboarding_versions import require_capability
    config = configuration()
    if not active(config):
        raise RuntimeError('Invalid or expired pilot configuration.')
    db = SessionLocal()
    try:
        for key in config.scopes:
            scope = TurnScope(**dict(zip(FIELDS, key)))
            _, project, lead, conversation = require_scoped_entities(db, scope)
            validate_target(db, conversation)
            assert_dispatchable(db, conversation)
            if project.is_demo or lead.consent_status != 'granted' or lead.is_opt_out or conversation.is_paused or lead.agent_status == 'human_control':
                raise RuntimeError('Pilot requires an active, consenting, non-demo test opportunity.')
            require_capability(project.profile)
        return len(config.scopes)
    finally:
        db.rollback()
        db.close()
