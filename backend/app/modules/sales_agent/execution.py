"""Task-local simulation adapters; never a production engine selector."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Simulation:
    company_id: str
    project_id: str
    conversation_id: str
    lead_id: str
    clock: datetime


_simulation = ContextVar('sales_simulation', default=None)


def simulation():
    return _simulation.get()


def simulated(scope=None):
    value = simulation()
    if not value:
        return False
    return scope is None or all(getattr(scope, key) == getattr(value, key)
                               for key in ('company_id', 'project_id', 'lead_id')) and (
        getattr(scope, 'conversation_id', getattr(scope, 'id', value.conversation_id)) == value.conversation_id)


def now(real_clock=None):
    return simulation().clock if simulation() else (real_clock or datetime).utcnow()


def permitted(lead):
    value = simulation()
    scoped = value and lead.id == value.lead_id and lead.company_id == value.company_id
    return lead.consent_status == 'granted' or bool(scoped and lead.consent_status == 'granted_simulation')


def channel(value):
    if value == 'simulation' and simulation():
        return 'sms'
    return value


@contextmanager
def sandbox(db, conversation, clock):
    from .dialogue_store import Scope, check_scope
    if conversation.channel != 'simulation':
        raise PermissionError('Simulation adapters require a dedicated in-app conversation.')
    scope = Scope(conversation.company_id, conversation.project_id, conversation.id, conversation.lead_id)
    check_scope(db, scope)
    token = _simulation.set(Simulation(scope.company_id, scope.project_id, scope.conversation_id, scope.lead_id, clock))
    try:
        yield
    finally:
        _simulation.reset(token)
