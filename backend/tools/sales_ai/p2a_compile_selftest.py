"""P2-A cached LangGraph regression: offline, no DB, LLM or external effects.

Run from /app/backend:
  python -m tools.sales_ai.p2a_compile_selftest
"""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch

from app.modules.sales_agent import coordinator_graph as graph
from app.modules.sales_agent.commercial_routing import ObservationDecision, BASES


class TestP2ACompiledGraph(unittest.TestCase):
    def test_reuse_exact_same_compiled_graph(self):
        first = graph.compiled_graph()
        self.assertIs(first, graph.compiled_graph())
        self.assertEqual(graph.VERSION, 'sales-coordinator-graph/4.0')

    def test_cold_start_compiles_once_even_with_parallel_threads(self):
        # Temporarily replace the cache, leaving the production cache intact.
        with patch.object(graph, '_COMPILED_GRAPH', None):
            with patch.object(graph, '_build_compiled_graph', wraps=graph._build_compiled_graph) as build:
                barrier = Barrier(12)
                def lookup(_):
                    barrier.wait(timeout=10)
                    return graph.compiled_graph()
                with ThreadPoolExecutor(max_workers=12) as pool:
                    results = list(pool.map(lookup, range(12)))
                self.assertEqual(build.call_count, 1)
                self.assertTrue(all(value is results[0] for value in results))

    def test_execute_never_builds_or_compiles_a_graph(self):
        src = inspect.getsource(graph.execute)
        tree = ast.parse(src)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn('StateGraph', names)
        self.assertNotIn('_build_compiled_graph', names)
        self.assertTrue(any(isinstance(n, ast.Attribute) and n.attr == 'ainvoke'
                            for n in ast.walk(tree)))
        self.assertTrue(any(isinstance(n, ast.keyword) and n.arg == 'context'
                            for n in ast.walk(tree)))


class TestP2AInvocationIsolation(unittest.IsolatedAsyncioTestCase):
    async def case(self, label, *, kind='mixed', direct=False, fail_at=None):
        visited = []
        hooks = []
        routes = []
        observations = []
        async def stage(name):
            # Interleave tasks to exercise independent context per invocation.
            await asyncio.sleep(0)
            visited.append(label + ':' + name)
            if fail_at == name:
                raise RuntimeError(label + ':failed:' + name)
        def callback(name):
            async def run():
                await stage(name)
            return run
        result = await graph.execute(None,
            interpret=callback('interpret'), plan=callback('plan'),
            observe=callback('observe'), fulfill=callback('fulfill'),
            route_after_plan=(lambda: graph.RouteDecision('fulfill', 'verified_opt_out'))
                             if direct else None,
            observation_after_plan=lambda: ObservationDecision(kind, BASES[kind]),
            on_route=routes.append, on_observation_route=observations.append,
            on_stage=lambda name, trace: hooks.append((label, name, list(trace))))
        return result, visited, hooks, routes, observations

    async def test_16_simultaneous_runs_preserve_routes_and_trace(self):
        kinds = tuple(BASES)
        runs = await asyncio.gather(*[
            self.case('lead-'+str(n), kind=kinds[n % len(kinds)], direct=(n % 4 == 0))
            for n in range(16)
        ])
        self.assertIs(graph.compiled_graph(), graph.compiled_graph())
        for i, (result, visited, hooks, routes, observations) in enumerate(runs):
            label = 'lead-' + str(i)
            path = ['interpret', 'plan', 'fulfill'] if i % 4 == 0 else [
                'interpret', 'plan', 'observe', 'fulfill']
            self.assertEqual(result['trace'], path)
            self.assertEqual(visited, [label+':'+name for name in path])
            self.assertEqual([name for _, name, _ in hooks], path)
            self.assertTrue(all(label_seen == label for label_seen, _, _ in hooks))
            self.assertEqual(len(routes), 1)
            if i % 4 == 0:
                self.assertIsNone(result['observation_route'])
                self.assertFalse(observations)
            else:
                kind = kinds[i % len(kinds)]
                self.assertEqual(result['observation_route']['kind'], kind)
                self.assertEqual(observations, [ObservationDecision(kind, BASES[kind])])

    async def test_failure_in_one_run_does_not_corrupt_other_run(self):
        failed, passed = await asyncio.gather(
            self.case('bad', fail_at='plan'),
            self.case('good', kind='materials'),
            return_exceptions=True)
        self.assertIsInstance(failed, RuntimeError)
        self.assertIn('bad:failed:plan', str(failed))
        result, visited, _, _, _ = passed
        self.assertEqual(result['trace'], ['interpret', 'plan', 'observe', 'fulfill'])
        self.assertEqual(visited[-1], 'good:fulfill')

    async def test_sequential_runs_do_not_reuse_previous_decision(self):
        direct, *_ = await self.case('first', direct=True)
        normal, *_ = await self.case('second', kind='information')
        self.assertEqual(direct['route']['after_plan'], 'fulfill')
        self.assertIsNone(direct['observation_route'])
        self.assertEqual(normal['route']['after_plan'], 'observe')
        self.assertEqual(normal['observation_route']['kind'], 'information')


class TestP2AProductionWiring(unittest.TestCase):
    def test_current_runtime_still_calls_execute_with_existing_hooks(self):
        path = Path(__file__).resolve().parents[2] / 'app/modules/sales_agent/active_service.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        matches = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == 'execute']
        self.assertEqual(len(matches), 1)
        self.assertTrue({'route_after_plan', 'on_route', 'observation_after_plan',
                         'on_observation_route', 'on_stage', 'interpret', 'plan',
                         'observe', 'fulfill'}.issubset({kw.arg for kw in matches[0].keywords}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
