"""P1-B read-only specialist routing regression (no DB, LLM or HTTP calls).

Run inside the API container:
  python -m tools.sales_ai.p1b_routing_selftest
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from app.modules.sales_agent.commercial_routing import (
    ObservationDecision, BASES, classify, VERSION,
)
from app.modules.sales_agent.coordinator_graph import (
    execute, RouteDecision, VERSION as GRAPH_VERSION,
)

CURRENT = 'synthetic-current-inbound'


def frame(*topics, extra_tasks=(), missing=False, status='pending',
          clarification=False, **directives):
    requests = [NS(topic=NS(value=topic), polarity='request') for topic in topics]
    tasks = [NS(topic=NS(value=topic), source_message_id=CURRENT, status=status,
                binding_status='resolved', alternative_group=None)
             for topic in topics]
    for topic in extra_tasks:
        tasks.append(NS(topic=NS(value=topic), source_message_id='previous-inbound',
                        status='pending', binding_status='resolved', alternative_group=None))
    u = NS(requests=requests, requires_clarification=clarification,
           visit=None, appointment_query=None, comparison=None, alternatives=[],
           constraints=[], releases=[], cancellation=None, reschedule=None,
           wait=None, moderation=None, personal_facts=[],
           preference_withdrawals=[], source_purposes=[], objections=[])
    for name, value in directives.items():
        setattr(u, name, value)
    state = NS(tasks=tasks, last_understanding=None if missing else u)
    return NS(state=state, plan={'questions': [], 'deferred_requests': []}, results=())


class TestP1BClassifier(unittest.TestCase):
    def assert_route(self, outcome, expected):
        result = classify(outcome, CURRENT)
        self.assertEqual(result, ObservationDecision(expected, BASES[expected]))
        self.assertEqual(result.basis, BASES[result.kind])

    def test_single_information_tasks(self):
        for topic in ('catalog', 'property_details', 'pricing', 'financing',
                      'inventory', 'location', 'delivery', 'amenities'):
            with self.subTest(topic=topic):
                self.assert_route(frame(topic), 'information')

    def test_multiple_independent_information_tasks(self):
        self.assert_route(frame('pricing', 'financing'), 'information')

    def test_material_task(self):
        self.assert_route(frame('materials'), 'materials')

    def test_appointment_only_with_current_visit(self):
        self.assert_route(frame('appointment', visit=NS(action='request')), 'appointments')
        self.assert_route(frame('appointment', visit=NS(action='confirm')), 'appointments')

    def test_existing_appointment_query(self):
        self.assert_route(frame('appointment', appointment_query=NS(kind='show')), 'appointments')

    def test_mixed_human_and_pricing_must_preserve_both(self):
        self.assert_route(frame('human', 'pricing'), 'mixed')
        self.assert_route(frame('human'), 'mixed')

    def test_mixed_visit_and_materials_never_assume_specialist_permissions(self):
        self.assert_route(frame('appointment', 'materials', visit=NS(action='request')), 'mixed')

    def test_or_groups_and_constraints_keep_general_pipeline(self):
        self.assert_route(frame('materials', alternatives=[NS(id='or1')]), 'mixed')
        self.assert_route(frame('pricing', constraints=[NS(topic='pricing')]), 'mixed')
        self.assert_route(frame('materials', releases=[NS(topic='materials')]), 'mixed')

    def test_explicit_clarification_routes_to_clarification_node(self):
        self.assert_route(frame('pricing', clarification=True), 'clarification')
        value = frame('materials', status='awaiting_user')
        self.assert_route(value, 'clarification')
        value = frame('pricing')
        value.plan['questions'].append({'reason': 'ambiguous_owner'})
        self.assert_route(value, 'clarification')

    def test_unresolved_mixed_control_is_conservative(self):
        self.assert_route(frame('human', 'pricing', clarification=True), 'mixed')

    def test_old_task_is_not_current_routing_evidence(self):
        self.assert_route(frame('materials', extra_tasks=('appointment', 'pricing')), 'materials')

    def test_unknown_or_missing_input_is_mixed(self):
        self.assert_route(frame('nonexistent'), 'mixed')
        self.assert_route(frame('pricing', missing=True), 'mixed')
        self.assertEqual(classify(None, CURRENT).kind, 'mixed')
        self.assertEqual(classify(frame('pricing'), CURRENT, active=False).kind, 'mixed')
        self.assertEqual(classify(frame('pricing'), 'foreign-inbound').kind, 'mixed')

    def test_already_observed_and_capacity_deferred_fall_back(self):
        outcome = frame('pricing')
        outcome.results = ('existing',)
        self.assert_route(outcome, 'mixed')
        outcome = frame('pricing')
        outcome.plan['deferred_requests'] = [{'topic': 'materials'}]
        self.assert_route(outcome, 'mixed')

    def test_no_side_effects(self):
        outcome = frame('pricing', 'financing')
        before = repr(outcome)
        self.assert_route(outcome, 'information')
        self.assertEqual(repr(outcome), before)


class TestP1BGraph(unittest.IsolatedAsyncioTestCase):
    async def scenario(self, kind='mixed', *, fail_at=None, direct=False,
                       override=None):
        trace, decisions, stages = [], [], []
        async def stage(name):
            trace.append(name)
            if fail_at == name:
                raise RuntimeError('synthetic failure in '+name)
        def cb(name):
            async def run():
                await stage(name)
            return run
        decision = (override if override is not None
                    else ObservationDecision(kind, BASES[kind]))
        result = await execute(None, interpret=cb('interpret'), plan=cb('plan'),
            observe=cb('observe'), fulfill=cb('fulfill'),
            route_after_plan=(lambda: RouteDecision('fulfill', 'verified_opt_out'))
                             if direct else None,
            observation_after_plan=lambda: decision,
            on_observation_route=decisions.append,
            on_stage=lambda name, done: stages.append((name, list(done))))
        return result, trace, decisions, stages

    async def test_every_specialist_executes_identical_guarded_observer_once(self):
        for kind in BASES:
            with self.subTest(kind=kind):
                result, trace, decisions, stages = await self.scenario(kind)
                self.assertEqual(trace, ['interpret', 'plan', 'observe', 'fulfill'])
                self.assertEqual(result['trace'], trace)
                self.assertEqual(result['observation_route'], {
                    'version': VERSION, 'kind': kind, 'basis': BASES[kind]})
                self.assertEqual(result['version'], GRAPH_VERSION)
                self.assertEqual(decisions, [ObservationDecision(kind, BASES[kind])])
                self.assertEqual([name for name, _ in stages], trace)

    async def test_direct_control_never_calls_observation_dispatcher(self):
        result, trace, decisions, _ = await self.scenario(direct=True)
        self.assertEqual(trace, ['interpret', 'plan', 'fulfill'])
        self.assertIsNone(result['observation_route'])
        self.assertEqual(decisions, [])

    async def test_invalid_observation_route_stops_before_fulfill(self):
        async def noop():
            pass
        for invalid in (None, 'information', ObservationDecision('unknown', 'fake'),
                        ObservationDecision('information', 'mixed_or_unclassified_tasks')):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError):
                    await execute(None, interpret=noop, plan=noop, observe=noop,
                                  fulfill=lambda: self.fail('fulfillment reached'),
                                  observation_after_plan=lambda value=invalid: value)

    async def test_observer_error_prevents_fulfillment(self):
        for kind in BASES:
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(RuntimeError, 'observe'):
                    await self.scenario(kind, fail_at='observe')


class TestP1BWiring(unittest.TestCase):
    def test_runtime_passes_classifier_and_audit_hooks_to_graph(self):
        runtime = Path(__file__).resolve().parents[2] / 'app/modules/sales_agent/active_service.py'
        tree = ast.parse(runtime.read_text(encoding='utf-8'))
        funcs = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        selector = [fn for fn in funcs if fn.name == 'observation_after_plan']
        audit = [fn for fn in funcs if fn.name == 'record_observation_route']
        self.assertEqual(len(selector), 1)
        self.assertEqual(len(audit), 1)
        self.assertTrue(any(isinstance(node, ast.Call) and
                            isinstance(node.func, ast.Name) and node.func.id == 'classify_observation'
                            for node in ast.walk(selector[0])))
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == 'execute' and {'observation_after_plan',
                            'on_observation_route', 'route_after_plan', 'on_route'}.issubset(
                                {kw.arg for kw in node.keywords}) for node in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
