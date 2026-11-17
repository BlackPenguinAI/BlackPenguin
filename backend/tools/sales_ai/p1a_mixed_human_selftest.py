"""Offline P1-A mixed human+commercial correction; no DB/LLM access."""
import ast
import json
import unittest
from pathlib import Path
from app.modules.sales_agent.mixed_human_visit import omit_spurious_visit

MIXED = 'I want to speak to a human. What is the price of Bay Residence?'
# The original first malformed provider response from the closing-point report.
RECORDED = json.loads('{"preferences":[],"personal_facts":[],"preference_withdrawals":[],"source_purposes":[],"objections":[],"empathy":null,"releases":[],"visit":{"action":"request","evidence":"I want to speak to a human.","timing":null},"courtesy":null,"reschedule":null,"cancellation":null,"wait":null,"moderation":null,"appointment_query":null,"requires_clarification":false,"clarification_question":null,"confidence":1,"version":"sales-interpretation-input/2.0","requests":[{"polarity":"request","evidence":"What is the price of Bay Residence?","target":{"kind":"property","expression":"Bay Residence","evidence":"Bay Residence"},"topic":"pricing","subject":null}],"alternatives":[],"constraints":[],"selection":null}')

class TestP1AMixedHuman(unittest.TestCase):
    def test_recorded_bad_visit_is_omitted_without_dropping_price(self):
        fixed, notes = omit_spurious_visit(RECORDED, MIXED)
        self.assertIsNone(fixed['visit'])
        self.assertEqual(fixed['requests'], RECORDED['requests'])
        self.assertEqual(fixed['confidence'], RECORDED['confidence'])
        self.assertFalse(notes[0]['effect_authorization'])
        self.assertEqual(RECORDED['visit']['action'], 'request')

    def test_genuine_visit_remains(self):
        msg = MIXED + ' I would also like to book a visit.'
        fixed, notes = omit_spurious_visit(RECORDED, msg)
        self.assertEqual((fixed,notes),(RECORDED,[]))

    def test_hypothetical_or_reported_request_is_not_repaired(self):
        for msg in ('If '+MIXED, 'My friend said: '+MIXED,
                    'I do not want to speak to a human. What is the price?'):
            with self.subTest(msg=msg):
                self.assertEqual(omit_spurious_visit(RECORDED,msg),(RECORDED,[]))

    def test_without_explicit_own_human_request_is_not_repaired(self):
        msg='What is the price of Bay Residence?'
        self.assertEqual(omit_spurious_visit(RECORDED,msg),(RECORDED,[]))

    def test_select_and_confirmation_never_changed(self):
        for action in ('select','confirm'):
            with self.subTest(action=action):
                record={**RECORDED,'visit':{**RECORDED['visit'],'action':action}}
                self.assertEqual(omit_spurious_visit(record,MIXED),(record,[]))

    def test_restrictions_and_other_topics_are_not_modified(self):
        record={**RECORDED,'constraints':[{'topic':'appointment','effect':'prohibit'}],
                'requests':[{'topic':'financing'},*RECORDED['requests']]}
        fixed,notes=omit_spurious_visit(record,MIXED)
        self.assertEqual(fixed['constraints'],record['constraints'])
        self.assertEqual(fixed['requests'],record['requests'])
        self.assertTrue(notes)

    def test_wire_compiler_references_negative_repair(self):
        compiler=Path(__file__).resolve().parents[2]/'app/modules/sales_agent/interpretation_input.py'
        tree=ast.parse(compiler.read_text(encoding='utf-8'))
        methods=[node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='compile_input']
        self.assertEqual(len(methods),1)
        body=methods[0]
        imported=any(isinstance(node,ast.ImportFrom) and node.module=='mixed_human_visit' and any(alias.name=='omit_spurious_visit' for alias in node.names) for node in ast.walk(body))
        called=any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='omit_spurious_visit' for node in ast.walk(body))
        self.assertTrue(imported and called)

if __name__ == '__main__':
    unittest.main(verbosity=2)
