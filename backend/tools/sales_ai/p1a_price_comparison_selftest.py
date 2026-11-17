"""Exact P1-A closing report regression; pure functions, no LLM or DB."""
import ast
import json
import unittest
from pathlib import Path
from app.modules.sales_agent.mixed_human_visit import omit_spurious_visit
from app.modules.sales_agent.mixed_human_pricing import (
    normalize_misread_price_comparison, verified_mixed_price_read,
)

MESSAGE = 'I want to speak to a human. What is the price of Bay Residence?'
RECORDED = json.loads("{\"preferences\": [], \"personal_facts\": [], \"preference_withdrawals\": [], \"source_purposes\": [], \"objections\": [], \"empathy\": null, \"releases\": [], \"visit\": {\"action\": \"request\", \"evidence\": \"I want to speak to a human.\", \"timing\": null}, \"courtesy\": null, \"reschedule\": null, \"cancellation\": null, \"wait\": null, \"moderation\": null, \"appointment_query\": null, \"requires_clarification\": false, \"clarification_question\": null, \"confidence\": 0, \"version\": \"sales-interpretation-input/2.0\", \"requests\": [{\"topic\": \"comparison\", \"polarity\": \"request\", \"evidence\": \"What is the price of Bay Residence?\", \"members\": [{\"kind\": \"property\", \"expression\": \"Bay Residence\", \"evidence\": \"What is the price of Bay Residence?\"}], \"include_current\": false, \"include_all\": false, \"all_kind\": \"property\", \"criteria\": [\"price\"], \"feature\": null, \"operation\": \"compare\"}], \"alternatives\": [], \"constraints\": [], \"selection\": null}")
NAMES = ['Bay Residence']
CATALOG = {'property_types': [{'id': 'synthetic-bay', 'property_type': 'Bay Residence'}]}


def normalized(data=None, message=MESSAGE, names=None):
    value = RECORDED if data is None else data
    without_visit, _ = omit_spurious_visit(value, message)
    return normalize_misread_price_comparison(without_visit, message,
                                             NAMES if names is None else names)


class TestP1AMixedPriceComparison(unittest.TestCase):
    def test_exact_provider_response_is_repaired(self):
        fixed, notes = normalized()
        self.assertIsNone(fixed['visit'])
        self.assertEqual(len(fixed['requests']), 1)
        self.assertEqual(fixed['requests'][0]['topic'], 'pricing')
        self.assertEqual(fixed['requests'][0]['target']['expression'], 'Bay Residence')
        self.assertEqual(fixed['requests'][0]['target']['evidence'], 'Bay Residence')
        self.assertEqual(fixed['requests'][0]['evidence'], 'What is the price of Bay Residence?')
        self.assertEqual(fixed['confidence'], 0)
        self.assertFalse(notes[0]['effect_authorization'])
        self.assertEqual(RECORDED['requests'][0]['topic'], 'comparison')
        self.assertEqual(RECORDED['visit']['action'], 'request')

    def test_approved_catalog_is_required_and_unique(self):
        for names in ([],['Other Property'], ['Bay Residence','Bay Residence']):
            with self.subTest(names=names):
                value, _ = omit_spurious_visit(RECORDED, MESSAGE)
                self.assertEqual(normalize_misread_price_comparison(value,MESSAGE,names),(value,[]))

    def test_genuine_comparison_is_unchanged(self):
        for text in ('I want to speak to a human. Compare Bay Residence with Cedar Loft.',
                     'What is cheaper, Bay Residence or Cedar Loft?',
                     MESSAGE + ' Also compare it with Cedar Loft.'):
            with self.subTest(text=text):
                self.assertEqual(normalize_misread_price_comparison(RECORDED,text,NAMES),(RECORDED,[]))

    def test_unsafe_or_reported_requests_are_unchanged(self):
        for text in ('If ' + MESSAGE, 'My friend said: ' + MESSAGE,
                     'I do not want to speak to a human. What is the price of Bay Residence?',
                     MESSAGE + ' Please book an appointment.'):
            with self.subTest(text=text):
                self.assertEqual(normalize_misread_price_comparison(RECORDED,text,NAMES),(RECORDED,[]))

    def test_appointment_or_other_effects_are_never_modified(self):
        value, _ = omit_spurious_visit(RECORDED, MESSAGE)
        for key,field in (('visit',{'action':'confirm'}),('cancellation',{'action':'cancel'}),
                          ('constraints',[{'topic':'pricing'}]),('alternatives',[{'evidence':'other'}]),
                          ('selection',{'kind':'property'})):
            with self.subTest(key=key):
                modified = {**value,key:field}
                self.assertEqual(normalize_misread_price_comparison(modified,MESSAGE,NAMES),(modified,[]))

    def test_other_topics_or_comparison_shapes_are_unchanged(self):
        value, _ = omit_spurious_visit(RECORDED, MESSAGE)
        for changed in ({'topic':'pricing'}, {'criteria':['bedrooms']},
                        {'include_all':True}, {'members':[]},
                        {'members':[{'kind':'unit','expression':'Bay Residence','evidence':'Bay Residence'}]}):
            with self.subTest(changed=changed):
                modified = {**value, 'requests': [{**value['requests'][0], **changed}]}
                self.assertEqual(normalize_misread_price_comparison(modified,MESSAGE,NAMES),(modified,[]))

    def test_no_new_model_permissions_or_confidence(self):
        value,_=omit_spurious_visit(RECORDED,MESSAGE)
        for conf in (0,0.12,0.95):
            with self.subTest(conf=conf):
                changed={**value,'confidence':conf}
                result,notes=normalize_misread_price_comparison(changed,MESSAGE,NAMES)
                self.assertEqual(result['confidence'],conf)
                self.assertFalse(notes[0]['effect_authorization'])
                self.assertEqual(len(result['requests']),len(changed['requests']))

    def test_compiler_wiring_uses_price_repair_after_visit_repair(self):
        source=Path(__file__).resolve().parents[2]/'app/modules/sales_agent/interpretation_input.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        compiler=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)
                      and node.name=='compile_input')
        called=[node.func.id for node in ast.walk(compiler) if isinstance(node,ast.Call)
                and isinstance(node.func,ast.Name)]
        self.assertIn('omit_spurious_visit',called)
        self.assertIn('normalize_misread_price_comparison',called)
        self.assertIn('canonicalize_new_visit',called)
        self.assertLess(called.index('omit_spurious_visit'),called.index('normalize_misread_price_comparison'))
        self.assertLess(called.index('normalize_misread_price_comparison'),called.index('canonicalize_new_visit'))


if __name__=='__main__':
    unittest.main(verbosity=2)
