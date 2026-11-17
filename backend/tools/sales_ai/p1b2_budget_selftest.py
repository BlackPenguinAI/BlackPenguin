"""P1-B.2 offline contracts: pure profiles; no provider, DB, or HTTP.

Run: python -m tools.sales_ai.p1b2_budget_selftest
"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from app.modules.sales_agent.observation_budget import (
    VERSION, for_turn, complete_information_batch,
)


def task(topic, status='pending', **extra):
    data = dict(topic=NS(value=topic), status=status, alternative_group=None)
    data.update(extra)
    return NS(**data)


def understanding(**overrides):
    data = dict(visit=None, appointment_query=None, comparison=None, constraints=[],
                releases=[], alternatives=[], cancellation=None, reschedule=None,
                wait=None, moderation=None, requires_clarification=False)
    data.update(overrides)
    return NS(**data)


class TestP1B2ReadBudgets(unittest.TestCase):
    def test_information_one_read_per_current_task(self):
        for topic in ('catalog', 'pricing', 'financing', 'inventory', 'property_details',
                      'delivery', 'amenities', 'location'):
            with self.subTest(topic=topic):
                profile = for_turn('information', [task(topic)], {}, understanding())
                self.assertEqual((profile.effective_kind, profile.max_reads, profile.legacy_max_reads),
                                 ('information', 1, 6))
                self.assertTrue(profile.single_pass_information)
        self.assertEqual(for_turn('information', [task('pricing'), task('financing')], {},
                                  understanding()).max_reads, 2)

    def test_material_and_appointment_include_necessary_followup_reads(self):
        self.assertEqual(for_turn('materials', [task('materials')], {}, understanding()).max_reads, 2)
        self.assertEqual(for_turn('appointments', [task('appointment')], {}, understanding()).max_reads, 2)
        self.assertEqual(for_turn('materials', [task('materials')]*5, {}, understanding()).max_reads, 6)

    def test_original_policy_ceiling_never_increases(self):
        for kind, tasks in [('information', [task('pricing')]),
                            ('materials', [task('materials')]),
                            ('appointments', [task('appointment')]),
                            ('mixed', [task('pricing'), task('human')])]:
            for max_steps, read_units in ((1, 12), (8, 2), (8, 12)):
                with self.subTest(kind=kind, max_steps=max_steps, read_units=read_units):
                    budget = for_turn(kind, tasks, {'limits':{'steps': max_steps,
                                                  'read_units': read_units}}, understanding())
                    self.assertLessEqual(budget.max_reads, budget.legacy_max_reads)
                    self.assertEqual(budget.legacy_max_reads, min(6, max_steps, read_units//2))

    def test_unknown_and_cross_domain_never_narrow_permissions(self):
        cases = [
            ('information', [task('pricing'), task('appointment')], understanding()),
            ('materials', [task('pricing')], understanding()),
            ('appointments', [task('materials')], understanding()),
            ('information', [task('pricing')], understanding(constraints=[NS(topic='pricing')])),
            ('information', [task('pricing', alternative_group='or1')], understanding()),
            ('unrecognized', [task('pricing')], understanding()),
        ]
        for kind, tasks, u in cases:
            # Fix the explicit alternative task without duplicate kwargs.
            p = for_turn(kind, tasks, {}, u)
            self.assertEqual((p.effective_kind, p.max_reads, p.single_pass_information),
                             ('mixed', 6, False))

    def test_single_pass_shortcut_only_when_all_verified(self):
        profile = for_turn('information', [task('pricing')], {}, understanding())
        options = dict(rounds=1,current_tasks=[task('pricing', 'completed')],available_tools={},
                       decisions=[{'status':'accepted','action':'read'}],
                       results=[NS(status='partial')],understanding=understanding())
        self.assertTrue(complete_information_batch(profile, **options))
        for key, variant in (
            ('rounds', 2),
            ('available_tools', {'read_remaining':{}}),
            ('current_tasks', [task('pricing', 'blocked')]),
            ('results', [NS(status='empty')]),
            ('decisions', [{'status':'decision_rejected','action':'read'}]),
            ('understanding', understanding(requires_clarification=True)),
            ('understanding', understanding(visit=NS(action='request'))),
        ):
            with self.subTest(case=key, variant=str(variant)):
                self.assertFalse(complete_information_batch(profile, **{**options, key:variant}))
        fallback = for_turn('mixed', [task('pricing')], {}, understanding())
        self.assertFalse(complete_information_batch(fallback, **options))
        self.assertEqual(VERSION, 'sales-observation-budget/1.0')

    def test_live_runtime_only_passes_graph_validated_route(self):
        root = Path(__file__).resolve().parents[2] / 'app/modules/sales_agent'
        tree = ast.parse((root / 'active_service.py').read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'observe_run']
        self.assertEqual(len(calls), 1)
        self.assertIn('observation_kind', {k.arg for k in calls[0].keywords})
        graph = (root / 'coordinator_graph.py').read_text(encoding='utf-8')
        self.assertIn("on_observation_route(decision)", graph)


if __name__ == '__main__':
    unittest.main(verbosity=2)
