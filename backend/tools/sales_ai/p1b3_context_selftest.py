"""P1-B.3 deterministic composition context regression; no LLM, DB or HTTP.

Run from the container:
    python -m tools.sales_ai.p1b3_context_selftest
"""
import ast
import copy
import json
from pathlib import Path
import unittest
import tempfile
from zipfile import ZipFile

from app.modules.sales_agent.composition_context import (
    project, VERSION, HISTORY_LIMIT,
)


def fixture():
    history = [{'message_id': str(i), 'role': 'user' if i % 2 else 'assistant',
                'content': ('Past context %d ' % i) * 35} for i in range(20)]
    return {
        'version': 'sales-commercial-composer/1.0',
        'published_guidance': {'guidance': {'segment': 'Be courteous'}, 'model': 'test/offline'},
        'current_message': 'Please show the approved price of Bay Residence.',
        'turn_context': {
            'history': history,
            'history_coverage': {'messages': 20, 'bounded': True},
            'current_interest': {'property_type_id': 'bay'},
            'appointments': {'active': {'count': 1, 'rows': [{'id': 'known-visit'}]}},
            'constraints': [{'topic': 'appointment', 'evidence': 'Do not book a visit'}],
            'property_constraints': [{'topic': 'materials', 'property_id': 'bay'}],
            'booking_proposal': {'id': 'receipt', 'expires_at': '2026-11-17T22:00:00Z'},
            'cancellation_proposal': {'id': 'no-action'},
            'reschedule_proposal': {'id': 'no-action'},
            'lead_profile': {'bedrooms': 4},
            'optional_profile': {'provided': True},
            'memory': {'answered_topics': ['pricing'], 'recent_turns': [{'id': 't1'}]},
            'pending_tasks': [{'topic': 'materials', 'status': 'pending'}],
        },
        'validated_results': [
            {'version': 'sales-tool-result/1.0', 'operation_id': 'op-price', 'status': 'success', 'safe_message': None,
             'data': {'property_types': [{'description': 'Catalog fact ' * 1500,
                                          'starting_price': 780000}],
                      'private_provider_token': 'must-not-enter-model'}},
        ],
        'planning': {'request_coverage': [{'request_id': 'r1', 'status': 'retained'}],
                     'pending_topics': ['materials'],
                     'questions': [{'request_id': 'r1', 'reason': 'choose-owner'}],
                     'deferred_requests': [],
                     'write_candidates_require_backend_authorization': [],
                     'references': {'huge': 'resolved ' * 1800},
                     'rounds': [{'feedback': 'old ' * 900}],
                     'context_sha256': 'a' * 64},
        'evidence_blocks': [
            {'id': 'e0', 'required': True, 'source': 'approved_pricing',
             'wordings': {'direct': 'Bay Residence starts at USD 780,000.'}},
            {'id': 'e1', 'required': False, 'source': 'policy',
             'wordings': {'direct': 'Prices are indicative.'}},
        ],
        'continuations': [{'id': 'none', 'text': '', 'metadata': {}},
                          {'id': 'details', 'text': 'Would you like details?', 'metadata': {}}],
        'style': 'Answer all current questions.',
    }


class TestP1B3CompositionContext(unittest.TestCase):
    def test_reduces_bytes_without_changing_authorized_output_vocabulary(self):
        payload = fixture()
        projected, stats = project(payload)
        for field in ('version', 'published_guidance', 'current_message',
                      'evidence_blocks', 'continuations', 'style'):
            self.assertEqual(projected[field], payload[field])
        self.assertEqual(stats['version'], VERSION)
        self.assertEqual(stats['mode'], 'projected')
        self.assertGreater(stats['saved_bytes'], 10000)
        self.assertEqual(stats['before_bytes']-stats['after_bytes'], stats['saved_bytes'])

    def test_never_drops_authoritative_continuity_or_restrictions(self):
        payload = fixture()
        projected, _ = project(payload)
        for field in ('current_interest', 'appointments', 'constraints',
                      'property_constraints', 'booking_proposal', 'cancellation_proposal',
                      'reschedule_proposal', 'lead_profile', 'optional_profile',
                      'memory', 'pending_tasks', 'history_coverage'):
            self.assertEqual(projected['turn_context'][field], payload['turn_context'][field])

    def test_history_is_recent_only_and_source_is_never_mutated(self):
        payload = fixture()
        original = copy.deepcopy(payload)
        projected, stats = project(payload)
        self.assertEqual(projected['turn_context']['history'], original['turn_context']['history'][-HISTORY_LIMIT:])
        self.assertEqual(stats['history_messages_omitted'], 20-HISTORY_LIMIT)
        self.assertEqual(payload, original)

    def test_tool_data_is_not_repeated_but_status_and_gaps_remain(self):
        projected, _ = project(fixture())
        self.assertEqual(projected['validated_results'], [
            {'version': 'sales-tool-result/1.0', 'operation_id': 'op-price', 'status': 'success', 'safe_message': None}
        ])
        self.assertNotIn('must-not-enter-model', json.dumps(projected))
        self.assertIn('USD 780,000', json.dumps(projected))

    def test_required_planning_coverage_and_questions_remain(self):
        payload = fixture()
        projected, _ = project(payload)
        for field in ('questions', 'pending_topics', 'request_coverage',
                      'deferred_requests', 'write_candidates_require_backend_authorization'):
            self.assertEqual(projected['planning'][field], payload['planning'][field])
        self.assertNotIn('references', projected['planning'])
        self.assertNotIn('rounds', projected['planning'])

    def test_unknown_future_contract_is_preserved(self):
        payload = fixture()
        payload['new_authoritative_field'] = {'must_keep': True}
        projected, stats = project(payload)
        self.assertEqual(projected, payload)
        self.assertEqual(stats['saved_bytes'], 0)
        self.assertEqual(stats['mode'], 'preserved_unknown_contract')

    def test_unknown_nested_planner_or_result_fields_are_preserved(self):
        for key in ('planning', 'validated_results'):
            payload = fixture()
            if key == 'planning':
                payload[key]['unreviewed_new_stage'] = {'authoritative': True}
            else:
                payload[key][0]['unreviewed_receipt'] = 'must-keep'
            projected, stats = project(payload)
            self.assertEqual(projected, payload)
            self.assertEqual(stats['mode'], 'preserved_unknown_contract')

    def test_unknown_shapes_are_not_silently_compacted(self):
        for malformed in [None, {}, {'history': 'not-an-array'}]:
            payload = fixture()
            payload['turn_context'] = malformed
            projected, stats = project(payload)
            self.assertEqual(projected, payload)
            self.assertEqual(stats['saved_bytes'], 0)

    def test_idempotent_projection_and_bounded_history(self):
        first, _ = project(fixture())
        second, stats = project(first)
        self.assertEqual(first, second)
        self.assertEqual(stats['saved_bytes'], 0)

    def test_cost_report_supports_both_real_suite_trace_shapes(self):
        from tools.sales_ai.p1b3_cost_report import summarize
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'small.zip'
            report = {'commit': 'synthetic', 'version': 'sales-closing-point/1.0',
                      'status': 'PASS', 'scenario_count': 1,
                      'summary': {'PASS': 2, 'FAIL': 0, 'BLOCKED': 0},
                      'provider_calls': 2, 'provider_usage': {
                          'prompt_tokens': 100, 'completion_tokens': 10,
                          'cost_usd': 0.00008, 'responses_with_cost': 2},
                      'cases': [{'case': 'demo', 'turns': [{
                          'input_trace': {'observation_loop': {'read_budget': {'saved_decision_calls': 1}}},
                          'output': {'metadata': {'composition': {'context_projection': {
                              'mode': 'projected', 'saved_bytes': 350, 'before_bytes': 800,
                              'after_bytes': 450}}}}}]}]}
            with ZipFile(path, 'w') as z:
                z.writestr('report.json', json.dumps(report))
            row = summarize(path)
            self.assertEqual(row['observation_decisions_saved'], 1)
            self.assertEqual(row['composition_prompt_bytes_saved'], 350)
            self.assertEqual(row['composition_context_projected_turns'], 1)
            self.assertEqual(row['provider_calls'], 2)
            self.assertEqual(row['quality_scope'], 'automated_checks_not_integral_dialogue_assessment')

    def test_composer_wiring_retains_full_context_hash_and_model_guardrails(self):
        path = Path(__file__).resolve().parents[2] / 'app/modules/sales_agent/commercial_composer.py'
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertIn('from .composition_context import project', source)
        self.assertIn('model_payload, projection_trace = project(redact(payload))', source)
        self.assertIn("'context_sha256': digest(payload)", source)
        self.assertIn("'context_projection': projection_trace", source)
        self.assertIn('schema = response_schema(blocks,choices)', source)
        self.assertIn("'evidence_blocks': blocks, 'continuations': choices", source)
        self.assertIsNotNone(tree)


if __name__ == '__main__':
    unittest.main(verbosity=2)
