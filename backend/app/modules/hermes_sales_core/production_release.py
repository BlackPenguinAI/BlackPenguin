"""Production runtime readiness, independent of the persisted Sales selector.
The deployment supplies transport identity; business authorization comes from
persisted jobs and the existing domain contracts, never a per-lead env list.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import os
import re
import time
from typing import Mapping
from uuid import UUID

FIELDS = ('company_id', 'project_id', 'lead_id', 'conversation_id')
READY_URL = 'http://bp-hermes:8080/internal/readiness'
_bound = ContextVar('hermes_live_scope', default=None)
_admin = ContextVar('hermes_admin_selection', default=False)
# Cache only an authenticated local HTTP readiness result; never a routing decision.
_health_cache = (None, 0.0, False)


@dataclass(frozen=True)
class Release:
    revision: str


def requested() -> bool:
    return (os.getenv('ENVIRONMENT') == 'production' and
            os.getenv('HERMES_RUNTIME_ROLE') in {'api', 'sdk'})


def scope_key(scope: Mapping | object) -> tuple[str, ...]:
    values = tuple(scope.get(k) if isinstance(scope, Mapping) else getattr(scope, k, getattr(scope, 'id', None) if k == 'conversation_id' else None) for k in FIELDS)
    if not all(isinstance(v, str) and str(UUID(v)) == v for v in values):
        raise ValueError('Exact canonical UUID scope required.')
    return values


def configuration() -> Release | None:
    """Parse deployment-owned transport configuration; no operator pilot values."""
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
        return Release(revision)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def allowed(scope: Mapping | object, config: Release | None = None) -> bool:
    """Structural identity only. The database supplies the actual authorization."""
    config = config if config is not None else configuration()
    try:
        scope_key(scope)
        return config is not None
    except (ValueError, TypeError, AttributeError):
        return False


def local_sdk_ready(config: Release | None) -> bool:
    if config is None or os.getenv('HERMES_RUNTIME_ROLE') != 'sdk':
        return False
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    return bool(key and key not in {'test-only', 'disabled', 'offline'})


def sdk_readiness() -> dict:
    """Authenticated private transport/DB/import preflight, not model/provider acceptance."""
    config = configuration()
    if not local_sdk_ready(config):
        raise RuntimeError('SDK configuration is not ready.')
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
    return {'status': 'ready', 'release': config.revision, 'mode': 'global', 'transport': 'private-sdk'}


def ready() -> bool:
    """Gate closed by default. API verifies exact authenticated SDK identity."""
    global _health_cache
    config = configuration()
    if config is None:
        return False
    if os.getenv('HERMES_RUNTIME_ROLE') == 'sdk':
        return local_sdk_ready(config)
    token = os.environ['HERMES_INTERNAL_TOKEN']
    cache_key = (config.revision, sha256(token.encode()).digest())
    now = time.monotonic()
    if _health_cache[0] == cache_key and now - _health_cache[1] < 2:
        return _health_cache[2]
    result = False
    try:
        import httpx
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0), follow_redirects=False, trust_env=False) as client:
            reply = client.get(READY_URL, headers={'Authorization': 'Bearer ' + token})
            result = reply.status_code == 200 and reply.json() == {
                'status': 'ready', 'release': config.revision, 'mode': 'global', 'transport': 'private-sdk'}
    except Exception:
        result = False  # fail closed; no provider credentials or errors in UI
    _health_cache = (cache_key, time.monotonic(), result)
    return result


def require_execution() -> None:
    """Called at existing preparation, operation, scheduling and dispatcher gates."""
    from .engine_selection import EngineUnavailable
    config = configuration()
    if config is None:
        raise EngineUnavailable('Hermes production runtime is not configured.')
    if _admin.get() and os.getenv('HERMES_RUNTIME_ROLE') == 'api' and _bound.get() is None:
        return
    if _bound.get() is None:
        raise EngineUnavailable('No bound Hermes execution scope.')


@contextmanager
def bind_scope(scope):
    """An exact persisted scope, never a caller-supplied freeform payload."""
    if not requested():
        yield
        return
    from .engine_selection import EngineUnavailable
    config = configuration()
    if config is None or not allowed(scope, config):
        raise EngineUnavailable('Hermes execution scope is invalid.')
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
    return {'hermes_release_mode': 'global' if config else 'closed',
            'hermes_routing_scope': 'all_eligible_sales_events',
            'hermes_global_certified': False}


def authorize_sdk_job(db, job_id, run_id):
    """Independently resolve and verify the persisted event and reserved run.
    lock_job rechecks the claimed job, authenticated inbound, event pin, active
    opportunity, and provider route. No request may supply its own scope.
    """
    from app.modules.sales_agent.models import AgentRun
    from .live_job import lock_job
    from .engine_selection import EngineUnavailable
    job, scope, conversation, lead, inbound = lock_job(db, job_id)
    run = db.get(AgentRun, run_id)
    pin = (inbound.metadata_json or {}).get('sales_engine_pin') or {}
    if (not run or run.status != 'running' or run.mode != 'live'
            or run.conversation_id != conversation.id or run.event_id != pin.get('event_id')
            or not str(run.graph_version).startswith('hermes')
            or run.prompt_configuration_id != pin.get('policy_version_id')
            or (run.input_snapshot or {}).get('message_id') != inbound.id
            or (run.input_snapshot or {}).get('sales_engine_pin') != pin):
        raise EngineUnavailable('SDK request does not identify the pinned reserved run.')
    validate_target(db, conversation)
    return {name: getattr(scope, name) for name in FIELDS}


def is_bound() -> bool:
    return requested() and _bound.get() is not None

def _digits(value):
    return re.sub(r'[^0-9]', '', value or '')

def validate_target(db, conversation):
    """Verify persisted tenant/opportunity identity and current Telnyx recipient.
    The existing live job and dispatcher retain consent, opt-out, approval,
    pause, policy, event-pin, and operation authorization checks. In particular
    do not reject STOP here before the deterministic opt-out handler sees it.
    """
    from .engine_selection import EngineUnavailable
    from app.modules.sales_crm.models import Lead
    from app.modules.sales_agent.provider_routes import parts
    if not allowed(conversation):
        raise EngineUnavailable('Invalid live scope.')
    assert_bound_scope(conversation)
    lead = db.query(Lead).filter_by(id=conversation.lead_id).populate_existing().one_or_none()
    route = parts(conversation)
    if (not lead or lead.is_demo or lead.deleted_at
            or lead.company_id != conversation.company_id or lead.project_id != conversation.project_id
            or not route or not _digits(lead.phone)
            or _digits(route[1]) != _digits(lead.phone)):
        raise EngineUnavailable('Live opportunity or destination changed.')
    return lead
