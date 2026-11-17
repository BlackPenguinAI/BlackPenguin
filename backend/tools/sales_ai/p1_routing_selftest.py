"""Offline P1-A state routing and LangGraph shape tests; no LLM or DB access.

Run from a deployed API container:
  python -m tools.sales_ai.p1_routing_selftest
"""
import asyncio
import unittest
from types import SimpleNamespace as NS
from app.modules.sales_agent.coordinator_graph import (
    RouteDecision, VERSION, MODE, control_route, execute,
)


def outcome(topic='opt_out', *, extra_tasks=(), clarification=False, results=(),
            evidence_id='synthetic-current-message'):
    understanding = NS(
        requests=[NS(topic=NS(value=topic), polarity='request')],
        requires_clarification=clarification,
    )
    tasks = [NS(topic=NS(value=topic), source_message_id=evidence_id)]
    tasks.extend(NS(topic=NS(value=item), source_message_id=evidence_id)
                 for item in extra_tasks)
    return NS(state=NS(last_understanding=understanding, tasks=tasks), results=results)


class TestP1ControlRouter(unittest.TestCase):
    def test_opt_out_can_take_direct_control_path(self):
        got = control_route(active=True, outcome=outcome('opt_out'),
                            inbound_id='synthetic-current-message', exact_stop=True)
        self.assertEqual(got, RouteDecision('fulfill', 'verified_opt_out'))

    def test_protected_handoff_can_take_direct_path(self):
        got = control_route(active=True, outcome=outcome('human'),
                            inbound_id='synthetic-current-message', protected=True)
        self.assertEqual(got, RouteDecision('fulfill', 'protected_handoff'))

    def test_pure_human_contact_can_take_direct_path(self):
        got = control_route(active=True, outcome=outcome('human'),
                            inbound_id='synthetic-current-message', pure_human=True)
        self.assertEqual(got, RouteDecision('fulfill', 'pure_human_handoff'))

    def test_booking_and_commercial_requests_always_observe(self):
        for topic in ('appointment', 'pricing', 'materials', 'catalog', 'inventory'):
            with self.subTest(topic=topic):
                got = control_route(active=True, outcome=outcome(topic),
                                    inbound_id='synthetic-current-message', protected=True)
                self.assertEqual(got.next_stage, 'observe')

    def test_control_with_unrelated_current_task_must_observe(self):
        got = control_route(active=True, outcome=outcome(extra_tasks=('materials',)),
                            inbound_id='synthetic-current-message', exact_stop=True)
        self.assertEqual(got.next_stage, 'observe')

    def test_unresolved_control_must_observe(self):
        got = control_route(active=True, outcome=outcome(clarification=True),
                            inbound_id='synthetic-current-message', exact_stop=True)
        self.assertEqual(got.next_stage, 'observe')

    def test_control_signal_and_interpretation_must_agree(self):
        self.assertEqual(control_route(active=True, outcome=outcome('human'),
            inbound_id='synthetic-current-message', exact_stop=True).next_stage, 'observe')
        self.assertEqual(control_route(active=True, outcome=outcome('opt_out'),
            inbound_id='synthetic-current-message', protected=True).next_stage, 'observe')

    def test_control_mixed_with_visit_directive_must_observe(self):
        mixed = outcome('human')
        mixed.state.last_understanding.visit = NS(action='request')
        got = control_route(active=True, outcome=mixed,
                            inbound_id='synthetic-current-message', protected=True)
        self.assertEqual(got.next_stage, 'observe')

    def test_observed_results_cannot_be_discarded(self):
        got = control_route(active=True, outcome=outcome(results=('already_observed',)),
                            inbound_id='synthetic-current-message', exact_stop=True)
        self.assertEqual(got.next_stage, 'observe')

    def test_historical_mode_keeps_normal_pipeline(self):
        got = control_route(active=False, outcome=outcome(),
                            inbound_id='synthetic-current-message', exact_stop=True)
        self.assertEqual(got.next_stage, 'observe')

    def test_missing_and_mixed_understanding_fail_closed(self):
        self.assertEqual(control_route(active=True, outcome=None,
                         inbound_id='synthetic-current-message', exact_stop=True).next_stage, 'observe')
        mixed = outcome('opt_out')
        mixed.state.last_understanding.requests.append(NS(topic=NS(value='materials'),polarity='request'))
        self.assertEqual(control_route(active=True, outcome=mixed,
                         inbound_id='synthetic-current-message', exact_stop=True).next_stage, 'observe')


class TestP1Wiring(unittest.TestCase):
    def test_production_runtime_wires_state_router(self):
        import ast
        from pathlib import Path
        runtime = Path(__file__).resolve().parents[2] / 'app/modules/sales_agent/active_service.py'
        tree = ast.parse(runtime.read_text(encoding='utf-8'))
        methods = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        router = [method for method in methods if method.name == 'route_after_plan']
        recorder = [method for method in methods if method.name == 'record_route']
        self.assertEqual(len(router), 1)
        self.assertEqual(len(recorder), 1)
        self.assertTrue(any(isinstance(node, ast.Call) and
                         isinstance(node.func, ast.Name) and node.func.id == 'control_route'
                         for node in ast.walk(router[0])))
        self.assertTrue(any(isinstance(node, ast.Call) and
                         isinstance(node.func, ast.Name) and node.func.id == 'execute' and
                         {'route_after_plan','on_route'}.issubset(
                             {kw.arg for kw in node.keywords})
                         for node in ast.walk(tree)))


class TestP1LangGraph(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, route=None, fail_at=None):
        events = []
        async def invoke(name):
            events.append(name)
            if name == fail_at:
                raise RuntimeError(f'synthetic error in {name}')
        def phase(name):
            async def cb():
                await invoke(name)
            return cb
        decisions = []
        result = await execute(None,
            interpret=phase('interpret'), plan=phase('plan'),
            observe=phase('observe'), fulfill=phase('fulfill'),
            route_after_plan=(lambda: route) if route is not None else None,
            on_route=decisions.append)
        return result, events, decisions

    async def test_default_path_preserves_every_stage(self):
        result, events, decisions = await self.scenario()
        self.assertEqual(events, ['interpret','plan','observe','fulfill'])
        self.assertEqual(result['trace'], events)
        self.assertEqual(result['version'], VERSION)
        self.assertEqual(result['mode'], MODE)
        self.assertEqual(result['route']['after_plan'], 'observe')
        self.assertEqual(len(decisions), 1)

    async def test_direct_control_bypasses_observation_only(self):
        result, events, decisions = await self.scenario(
            RouteDecision('fulfill', 'verified_opt_out'))
        self.assertEqual(events, ['interpret','plan','fulfill'])
        self.assertEqual(result['trace'], events)
        self.assertEqual(result['route']['reason'], 'verified_opt_out')
        self.assertEqual(len(decisions), 1)

    async def test_unrecognized_route_blocks_fulfillment(self):
        async def noop():
            pass
        for invalid in (None, 'fulfill', RouteDecision('fulfill','commercial_observation'),
                        RouteDecision('skip','verified_opt_out'), RouteDecision('fulfill','unknown')):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError):
                    await execute(None,interpret=noop,plan=noop,observe=noop,
                                  fulfill=lambda: self.fail('fulfillment was called'),
                                  route_after_plan=lambda value=invalid: value)

    async def test_stage_failures_cannot_continue_downstream(self):
        for stage in ('interpret','plan','observe','fulfill'):
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(RuntimeError, stage):
                    await self.scenario(fail_at=stage)

    async def test_missing_observation_is_rejected(self):
        async def noop():
            pass
        with self.assertRaises(ValueError):
            await execute(None,interpret=noop,plan=noop,observe=None,fulfill=noop)


if __name__ == '__main__':
    unittest.main(verbosity=2)
