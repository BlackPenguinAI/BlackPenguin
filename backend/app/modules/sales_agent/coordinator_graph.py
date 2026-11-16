"""Single LangGraph coordinator for live and synthetic commercial turns.

Scoped database events/receipts own state; the graph never bypasses effect
permissions. Historical orchestration names are rejected, not fallback engines.
"""
from contextlib import contextmanager
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

VERSION = 'sales-coordinator-graph/2.0'
MODE = 'graph-observe'
MODES = (MODE,)

@contextmanager
def experiment(mode=MODE):
    """Compatibility context for laboratory callers; no engine selector."""
    if mode != MODE:
        raise ValueError('Only graph-observe is supported for commercial conversations.')
    yield

class State(TypedDict):
    trace: list[str]

async def execute(scope, *, interpret, plan, fulfill, observe, assess=None, reconsider=None, on_stage=None):
    """Same topology in live traffic and simulations, without a classic branch."""
    if observe is None:
        raise ValueError('The commercial graph requires an observation callback.')
    def node(name, callback):
        async def invoke(state):
            if on_stage is not None:on_stage(name, state['trace'])
            await callback()
            return {'trace': [*state['trace'], name]}
        return invoke
    graph = StateGraph(State)
    stages = [('interpret', interpret), ('plan', plan), ('observe', observe), ('fulfill', fulfill)]
    for name, callback in stages:
        graph.add_node(name, node(name, callback))
    graph.add_edge(START, 'interpret')
    for (before, _), (after, _) in zip(stages, stages[1:]):
        graph.add_edge(before, after)
    graph.add_edge('fulfill', END)
    state = await graph.compile().ainvoke({'trace': []}, config={'recursion_limit': 8})
    return {'version': VERSION, 'mode': MODE, 'trace': state['trace'], 'reconsiderations': 0, 'status': 'completed'}

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
