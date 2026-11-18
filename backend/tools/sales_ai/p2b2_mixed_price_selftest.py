"""Offline P2-B.2 semantic regression tests. No models, networking or DB writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.modules.sales_agent.interpretation_input import ProviderInput
from .p2b2_mixed_price_equivalence import (
    CASES, PRICE_MESSAGE, PRICE_QUESTION, REPAIR, Case,
    evaluate_case, input_document, recorded_replay, report,
)
from .p2b_repair_selftest import synthetic_bundle


class TestP2B2MixedPriceEquivalence(unittest.TestCase):
    def test_targeted_v3_and_v2_model_misreads_need_repair(self):
        for case in (c for c in CASES if c.should_repair):
            with self.subTest(case=case.code):
                r=evaluate_case(case)
                self.assertTrue(r['changed'])
                self.assertTrue(r['normalizer_triggered'])

    def test_correct_price_and_true_comparison_keep_their_meanings(self):
        for case in (c for c in CASES if c.kind=='pricing' or c.members):
            with self.subTest(case=case.code):
                self.assertFalse(evaluate_case(case)['changed'])

    def test_untrusted_ambiguous_context_and_multiple_actions_do_not_auto_repair(self):
        for case in (c for c in CASES if not c.should_repair and c.kind!='pricing' and not c.members):
            with self.subTest(case=case.code):
                self.assertFalse(evaluate_case(case)['normalizer_triggered'])

    def test_provider_v3_rejects_misread_comparison_in_root_requests(self):
        case=next(c for c in CASES if c.code=='v3_one_property_price_misread')
        packet=json.loads(input_document(case))
        comparison=packet.pop('comparison')
        packet['requests']=[comparison]
        with self.assertRaises(ValueError):ProviderInput.model_validate(packet)

    def test_no_unknown_external_effect_or_confidence_promotion(self):
        # evaluate_case asserts evidence, no visit/cancel/reschedule/wait,
        # no appointment or opt-out permission, and unchanged confidence.
        for case in CASES:
            with self.subTest(case=case.code):
                self.assertTrue(evaluate_case(case)['validated'])

    def test_ablated_repair_is_a_semantic_regression_not_merely_a_json_difference(self):
        from app.modules.sales_agent.interpretation_input import compile_input
        from .p2b_repair_ablation import noop
        case=next(c for c in CASES if c.code=='v3_one_property_price_misread')
        raw=input_document(case)
        with patch(REPAIR,side_effect=noop):
            wrong,_=compile_input(raw,case.text,approved_names=case.approved_names)
        right,_=compile_input(raw,case.text,approved_names=case.approved_names)
        self.assertIsNotNone(wrong.comparison)
        self.assertFalse(wrong.permits('pricing'))
        self.assertIsNone(right.comparison)
        self.assertTrue(right.permits('pricing'))
        self.assertFalse(right.permits('appointment'))
        self.assertEqual(right.requests[0].evidence,PRICE_QUESTION)

    def test_report_does_not_leak_packets_or_user_text(self):
        value=report()
        self.assertEqual(value['decision'],'KEEP_REPAIR')
        self.assertFalse(value['safe_to_remove'])
        self.assertGreaterEqual(value['targeted_misreads_repaired'],3)
        self.assertEqual(value['synthetic_cases'],len(CASES))
        serialized=json.dumps(value)
        self.assertNotIn(PRICE_MESSAGE,serialized)
        self.assertNotIn('raw_response',serialized)

    def test_archived_replay_with_truncated_packet_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path=synthetic_bundle(Path(folder)/'synthetic.zip',truncated=True)
            result=recorded_replay([path])
            self.assertEqual(result['replayable'],0)
            self.assertEqual(result['skipped']['missing_or_truncated_packet'],1)
            self.assertTrue(result['insufficient_for_removal'])

    def test_report_output_does_not_overwrite_synthetic_evidence(self):
        import argparse
        from .p2b2_mixed_price_equivalence import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'summary.json'
            self.assertEqual(main(['--output',str(path)]),0)
            content=json.loads(path.read_text())
            self.assertEqual(content['decision'],'KEEP_REPAIR')


if __name__=='__main__':unittest.main(verbosity=2)
