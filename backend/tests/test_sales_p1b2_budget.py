"""P1-B.2 offline budgets and one real scoped read without model/network use."""
import asyncio
import json
from datetime import datetime
import pytest
from tools.sales_ai.p1b2_budget_selftest import TestP1B2ReadBudgets  # noqa: F401
from test_sales_observation_loop import prepared
from test_sales_booking_pilot import lab  # noqa: F401
from app.modules.sales_agent.execution import sandbox
from app.modules.sales_agent.observation_loop import run


@pytest.mark.parametrize('kind,expected_calls,expected_saved', [
    ('information', 1, 1),
    ('mixed', 2, 0),
])
def test_catalog_read_uses_same_scoped_gateway_but_elides_redundant_decision(
        lab, kind, expected_calls, expected_saved):
    db, scope, conv, inbound, outcome = prepared(
        lab, 'What properties are available?', ('catalog',))
    observed = []

    async def infer(messages, schema):
        payload = json.loads(messages[1]['content'])
        observed.append(payload)
        tools = list(payload['available_tools'])
        return json.dumps({'action': 'read' if tools else 'respond',
                           'tool_ids': tools[:4]})

    with sandbox(db, conv, datetime.utcnow()):
        outcome, audit = asyncio.run(run(
            db, scope, inbound=inbound, outcome=outcome,
            commercial={}, infer=infer, observation_kind=kind))

    assert audit['status'] == 'PASS'
    assert audit['external_writes'] == 0
    assert len(audit['tools']) == 1
    assert audit['tools'][0]['external_writes'] == 0
    assert audit['read_budget']['effective_kind'] == kind
    assert audit['read_budget']['saved_decision_calls'] == expected_saved
    assert len(observed) == expected_calls
    assert outcome.plan['additional_model_calls'] == expected_calls
    assert audit['read_budget']['decision_prompt_bytes']
    assert all(t.status == 'completed' for t in outcome.state.tasks
               if t.source_message_id == inbound.id)
