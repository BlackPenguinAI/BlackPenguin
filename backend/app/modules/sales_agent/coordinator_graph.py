"""State-routed LangGraph coordinator for live and synthetic sales turns.

Scoped database events/receipts own state; the graph never bypasses effect
permissions. Historical orchestration names are rejected, not fallback engines.
Only audited, read-free control turns may bypass observation. Commercial
requests retain the proven observation and authorization pipeline.
P1-B selects specialized read-only graph nodes from the current persisted tasks;
every node delegates to the same bounded observation engine.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Awaitable, Callable, Literal, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.runtime import Runtime
from .commercial_routing import ObservationDecision, BASES as OBSERVATION_BASES, VERSION as OBSERVATION_VERSION

VERSION = 'sales-coordinator-graph/4.0'
MODE = 'graph-observe'
MODES = (MODE,)
ROUTES = frozenset({'observe', 'fulfill'})
REASONS = frozenset({'default_observation', 'commercial_observation', 'unsafe_control_observation',
                     'verified_opt_out', 'protected_handoff', 'pure_human_handoff'})
CONTROL_TOPICS = frozenset({'opt_out', 'human'})


@contextmanager
def experiment(mode=MODE):
    """Compatibility context for laboratory callers; no engine selector."""
    if mode != MODE:
        raise ValueError('Only graph-observe is supported for commercial conversations.')
    yield


@dataclass(frozen=True)
class RouteDecision:
    next_stage: Literal['observe', 'fulfill']
    reason: str


class State(TypedDict):
    trace: list[str]
    route: str
    route_reason: str
    observation_kind: str
    observation_basis: str


def control_route(*, active, outcome, inbound_id, exact_stop=False,
                  protected=False, pure_human=False):
    """Conservative, backend-state-only routing; never infers user intent.

    A control bypass cannot be requested by a model or by a lead message.
    Interpret and plan have already run, and fulfill still performs every
    existing scope, policy, consent and transaction check. A mixed commercial
    request, an unresolved interpretation or a pending non-control task must
    go through normal observation.
    """
    if not active or not (exact_stop or protected or pure_human):
        return RouteDecision('observe', 'commercial_observation')
    state = getattr(outcome, 'state', None)
    u = getattr(state, 'last_understanding', None)
    if state is None or u is None or u.requires_clarification or getattr(outcome, 'results', ()):
        return RouteDecision('observe', 'unsafe_control_observation')
    topics = {request.topic.value for request in u.requests}
    if (not topics or not topics.issubset(CONTROL_TOPICS) or
            any(getattr(u, field, None) for field in
                ('visit', 'reschedule', 'cancellation', 'wait', 'appointment_query',
                 'constraints', 'releases', 'alternatives'))):
        return RouteDecision('observe', 'unsafe_control_observation')
    if any(task.topic.value not in CONTROL_TOPICS for task in state.tasks
           if task.source_message_id == inbound_id):
        return RouteDecision('observe', 'unsafe_control_observation')
    # A control signal and its scoped interpreted topic must agree.
    if (exact_stop and topics != {'opt_out'}) or (
            not exact_stop and (protected or pure_human) and topics != {'human'}):
        return RouteDecision('observe', 'unsafe_control_observation')
    if exact_stop:
        return RouteDecision('fulfill', 'verified_opt_out')
    if protected:
        return RouteDecision('fulfill', 'protected_handoff')
    return RouteDecision('fulfill', 'pure_human_handoff')


@dataclass(frozen=True)
class TurnCallbacks:
    """Per-invocation dependencies, not graph state or process-global handlers.

    The callbacks may close over a conversation's SQLAlchemy session and scoped
    records. They must only be accessed through the current LangGraph Runtime.
    Never put this object in State or retain it on the compiled graph.
    """
    interpret: Callable[[], Awaitable[None]]
    plan: Callable[[], Awaitable[None]]
    observe: Callable[[], Awaitable[None]]
    fulfill: Callable[[], Awaitable[None]]
    on_stage: Callable[[str, list[str]], None] | None = None
    route_after_plan: Callable[[], RouteDecision] | None = None
    on_route: Callable[[RouteDecision], None] | None = None
    observation_after_plan: Callable[[], ObservationDecision] | None = None
    on_observation_route: Callable[[ObservationDecision], None] | None = None


def _build_compiled_graph():
    """Define the stable topology and compile it without capturing turn data."""
    def node(name):
        async def invoke(state: State, runtime: Runtime[TurnCallbacks]):
            callbacks = runtime.context
            if callbacks.on_stage is not None:
                callbacks.on_stage(name, state['trace'])
            await getattr(callbacks, name)()
            return {'trace': [*state['trace'], name]}
        return invoke

    async def choose_route(state: State, runtime: Runtime[TurnCallbacks]):
        callbacks = runtime.context
        decision = (callbacks.route_after_plan() if callbacks.route_after_plan is not None
                    else RouteDecision('observe', 'default_observation'))
        if (type(decision) is not RouteDecision or decision.next_stage not in ROUTES
                or decision.reason not in REASONS
                or (decision.next_stage == 'fulfill' and decision.reason not in
                    {'verified_opt_out', 'protected_handoff', 'pure_human_handoff'})):
            raise ValueError('Invalid coordinator routing decision; fulfillment blocked.')
        if callbacks.on_route is not None:
            callbacks.on_route(decision)
        return {'route': decision.next_stage, 'route_reason': decision.reason}

    async def choose_observation(state: State, runtime: Runtime[TurnCallbacks]):
        # Invalid labels still fail closed. All specialists use the same guarded
        # observation engine; routing never grants a business capability.
        callbacks = runtime.context
        decision = (callbacks.observation_after_plan() if callbacks.observation_after_plan is not None
                    else ObservationDecision('mixed', OBSERVATION_BASES['mixed']))
        if (type(decision) is not ObservationDecision or
                OBSERVATION_BASES.get(decision.kind) != decision.basis):
            raise ValueError('Invalid commercial observation route; fulfillment blocked.')
        if callbacks.on_observation_route is not None:
            callbacks.on_observation_route(decision)
        return {'observation_kind': decision.kind, 'observation_basis': decision.basis}

    graph = StateGraph(State, context_schema=TurnCallbacks)
    for name in ('interpret', 'plan', 'fulfill'):
        graph.add_node(name, node(name))
    graph.add_node('route', choose_route)
    graph.add_node('route_observation', choose_observation)
    for kind in OBSERVATION_BASES:
        graph.add_node('observe_' + kind, node('observe'))
        graph.add_edge('observe_' + kind, 'fulfill')
    graph.add_edge(START, 'interpret')
    graph.add_edge('interpret', 'plan')
    graph.add_edge('plan', 'route')
    graph.add_conditional_edges('route', lambda state: state['route'],
                                {'observe': 'route_observation', 'fulfill': 'fulfill'})
    graph.add_conditional_edges('route_observation',
                                lambda state: state['observation_kind'],
                                {kind: 'observe_' + kind for kind in OBSERVATION_BASES})
    graph.add_edge('fulfill', END)
    return graph.compile()


# Each API/worker process owns its own immutable topology. The lock ensures a
# concurrent cold start cannot compile more than once in the same process.
_COMPILE_LOCK = Lock()
_COMPILED_GRAPH = None


def compiled_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        with _COMPILE_LOCK:
            if _COMPILED_GRAPH is None:
                _COMPILED_GRAPH = _build_compiled_graph()
    return _COMPILED_GRAPH


async def execute(scope, *, interpret, plan, fulfill, observe, assess=None,
                  reconsider=None, on_stage=None, route_after_plan=None,
                  on_route=None, observation_after_plan=None,
                  on_observation_route=None):
    """Invoke the process-cached topology with isolated callbacks for this turn.

    The public signature, route/trace metadata and authorization boundaries are
    unchanged. The unused compatibility arguments do not enter graph context.
    """
    if observe is None:
        raise ValueError('The commercial graph requires an observation callback.')
    callbacks = TurnCallbacks(
        interpret=interpret, plan=plan, observe=observe, fulfill=fulfill,
        on_stage=on_stage, route_after_plan=route_after_plan, on_route=on_route,
        observation_after_plan=observation_after_plan,
        on_observation_route=on_observation_route)
    state = await compiled_graph().ainvoke(
        {'trace': [], 'route': 'observe', 'route_reason': 'default_observation',
         'observation_kind': 'mixed', 'observation_basis': OBSERVATION_BASES['mixed']},
        context=callbacks, config={'recursion_limit': 10})
    return {'version': VERSION, 'mode': MODE, 'trace': state['trace'],
            'route': {'after_plan': state['route'], 'reason': state['route_reason']},
            'observation_route': ({'version': OBSERVATION_VERSION,
                'kind': state['observation_kind'], 'basis': state['observation_basis']}
                if state['route'] == 'observe' else None),
            'reconsiderations': 0, 'status': 'completed'}


def reconsider_reason(value,text):
    """Only a low-confidence, single informational material request can retry."""
    import re
    from app.modules.governance.services import request_attribution
    if value.confidence>=.8 or value.constraints or value.alternatives or value.releases or value.comparison:return None
    if request_attribution(text)['current_text']!=text or re.search(r"\b(?:not|never|don.t|if|suppose|friend|said|told)\b",text,re.I):return None
    if any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query','personal_facts','preferences','preference_withdrawals','objections')):return None
    if len(value.requests)!=1 or not value.permits('materials'):return None
    return 'low_confidence_material_request'


def safe_candidate(original,candidate):
    """Reconsideration never broadens topics, adds restrictions or grants actions."""
    if candidate.confidence<.8 or candidate.requires_clarification:return False
    if len(candidate.requests)!=1 or not candidate.permits('materials'):return False
    if candidate.requests[0].subject!=original.requests[0].subject:return False
    fields=('visit','reschedule','cancellation','wait','moderation','appointment_query','comparison','constraints','alternatives','releases','preferences','personal_facts','preference_withdrawals','source_purposes','objections')
    return not any(getattr(candidate,k) for k in fields)
