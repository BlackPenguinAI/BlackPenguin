"""Explicit experimental orchestration over the same production services.

No checkpointer owns business state: existing scoped events/receipts remain
canonical. Only a task-local sandbox may choose a candidate mode. Production
uses the sequential reference until observed comparison has been reviewed.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from typing import TypedDict
from langgraph.graph import StateGraph,START,END

VERSION='sales-coordinator-graph/1.0'
_mode=ContextVar('sales_coordinator_mode',default='classic')
MODES=('classic','graph','graph-reconsider','graph-observe')

@contextmanager
def experiment(mode):
    if mode not in MODES:raise ValueError('Unknown coordinator mode.')
    token=_mode.set(mode)
    try:yield
    finally:_mode.reset(token)

class State(TypedDict):
    trace:list[str]
    reconsiderations:int
    retry:bool

async def execute(scope,*,interpret,assess,reconsider,plan,fulfill,observe=None):
    mode=_mode.get()
    if mode=='classic':
        await interpret();await plan();await fulfill()
        return {'version':VERSION,'mode':mode,'trace':['interpret','plan','fulfill'],'reconsiderations':0}
    from .execution import simulated
    if not simulated(scope):raise PermissionError('Candidate graphs require a scoped simulation.')
    def node(name,callback):
        async def invoke(state):
            await callback()
            return {'trace':[*state['trace'],name]}
        return invoke
    async def assess_node(state):
        retry=bool(mode=='graph-reconsider' and state['reconsiderations']==0 and assess())
        return {'trace':[*state['trace'],'assess'],'retry':retry}
    async def reconsider_node(state):
        await reconsider()
        return {'trace':[*state['trace'],'reconsider'],'reconsiderations':state['reconsiderations']+1}
    g=StateGraph(State)
    g.add_node('interpret',node('interpret',interpret));g.add_node('assess',assess_node)
    g.add_node('reconsider',reconsider_node);g.add_node('plan',node('plan',plan));g.add_node('fulfill',node('fulfill',fulfill))
    g.add_edge(START,'interpret');g.add_edge('interpret','assess')
    g.add_conditional_edges('assess',lambda s:'reconsider' if s['retry'] else 'plan')
    g.add_edge('reconsider','assess')
    if mode=='graph-observe':
        if observe is None:raise ValueError('Observation mode requires a real observation callback.')
        g.add_node('observe',node('observe',observe));g.add_edge('plan','observe');g.add_edge('observe','fulfill')
    else:g.add_edge('plan','fulfill')
    g.add_edge('fulfill',END)
    state=await g.compile().ainvoke({'trace':[],'reconsiderations':0,'retry':False},config={'recursion_limit':10})
    return {'version':VERSION,'mode':mode,'trace':state['trace'],'reconsiderations':state['reconsiderations']}


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
