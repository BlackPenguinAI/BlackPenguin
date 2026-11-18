"""P1-C: provider v3 vs archived v2 interpretation regression; offline only.

No database, network, LLM or external side effects. Run in deployed API:
  python -m tools.sales_ai.p1c_interpretation_selftest
"""
import json
import unittest
from pydantic import ValidationError
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.interpretation_input import (
    Input, ProviderInput, VERSION, PROVIDER_VERSION, compile_input, schema,
)


def packet(*, text, requests=(), comparison=None, alternatives=(), constraints=(), selection=None):
    base = Understanding.model_validate({
        'version': 'sales-understanding/1.0', 'requests': [], 'all_of': [],
        'alternatives': [], 'constraints': [], 'references': [],
        'preferences': [], 'requires_clarification': False,
        'clarification_question': None, 'confidence': 0.96,
    }).model_dump(mode='json')
    for key in ('version', 'requests', 'all_of', 'alternatives', 'references',
                'constraints', 'comparison', 'selected_reference_id'):
        base.pop(key, None)
    base.update(version=PROVIDER_VERSION, requests=list(requests),
                comparison=comparison, alternatives=list(alternatives),
                constraints=list(constraints), selection=selection)
    return ProviderInput.model_validate(base).model_dump(mode='json')


def information(topic, evidence, **more):
    return dict(topic=topic, polarity='request', subject=None, evidence=evidence,
                target=None, **more)


def target(name):
    return {'kind': 'property', 'expression': name, 'evidence': name}


class TestP1CProviderSchema(unittest.TestCase):
    def test_provider_has_three_root_request_shapes_not_five(self):
        root = schema('What financing options do you offer?')
        refs = root['properties']['requests']['items']['anyOf']
        names = {ref['$ref'].split('/')[-1] for ref in refs}
        self.assertEqual(names, {'ProviderInformationRequest', 'DetailRequest', 'MaterialRequest'})
        self.assertIn('comparison', root['properties'])
        self.assertIn('comparison', root['required'])
        self.assertNotIn('references', root['properties'])
        self.assertFalse(root['additionalProperties'])
        self.assertIn('financing', root['$defs']['ProviderInformationRequest']['properties']['topic']['enum'])
        self.assertIn('catalog', root['$defs']['ProviderInformationRequest']['properties']['topic']['enum'])
        self.assertEqual(len(root['$defs']['ProviderAlternativeGroup']['properties']['requests']['items']['anyOf']),4)

    def test_invalid_comparison_in_independent_requests_is_rejected(self):
        text='What financing options do you offer?'
        value=packet(text=text, requests=[information('financing', text)])
        value['requests']=[{'topic':'comparison','polarity':'request',
                            'evidence':text,'members':[],'criteria':['general']}]
        with self.assertRaises(ValidationError):
            ProviderInput.model_validate(value)
        with self.assertRaises(ValidationError):
            compile_input(json.dumps(value),text)

    def test_no_provider_supplied_database_or_request_ids(self):
        text='Show me Cedar Studio.'
        value=packet(text=text, requests=[information('inventory',text)])
        value['requests'][0]['reference_id']='db-record-id'
        with self.assertRaises(ValidationError):ProviderInput.model_validate(value)


class TestP1CCompiler(unittest.TestCase):
    def test_three_observed_financing_errors_have_unambiguous_v3_shape(self):
        quotes=(
            ('I do not want a visit yet. What financing options do you offer?',
             'What financing options do you offer?'),
            ('What financing options do you offer?', 'What financing options do you offer?'),
            ('What financing options do you offer?', 'What financing options do you offer?'),
        )
        for text,quote in quotes:
            with self.subTest(text=text):
                raw=json.dumps(packet(text=text,requests=[information('financing',quote)]))
                contract,notes=compile_input(raw,text)
                self.assertIsNone(contract.comparison)
                self.assertTrue(contract.permits('financing'))
                self.assertTrue(any(r.topic.value=='financing' and r.evidence==quote
                                    for r in contract.requests))
                self.assertFalse(contract.permits('appointment'))
                contract.check_evidence(text)

    def test_comparison_and_independent_financing_are_both_preserved(self):
        text='Compare Cedar Studio and Cedar Loft. What financing options do you offer?'
        compare={
            'topic':'comparison','polarity':'request',
            'evidence':'Compare Cedar Studio and Cedar Loft.',
            'members':[target('Cedar Studio'),target('Cedar Loft')],
            'criteria':['general'], 'include_current':False, 'include_all':False,
            'all_kind':'property','feature':None,'operation':'compare',
        }
        value=packet(text=text,requests=[information('financing','What financing options do you offer?')],
                     comparison=compare)
        contract,_=compile_input(json.dumps(value),text)
        self.assertTrue(contract.permits('financing'))
        self.assertTrue(contract.permits('catalog'))
        self.assertIsNotNone(contract.comparison)
        self.assertEqual(len(contract.comparison.reference_ids),2)
        self.assertEqual(len(contract.requests),2)
        self.assertEqual(len(contract.all_of),2)
        self.assertIsNone(contract.selected_reference_id)
        self.assertIsNone(contract.visit)
        contract.check_evidence(text)

    def test_material_or_and_financing_remain_independent(self):
        text='Send photos or a brochure and explain financing options.'
        quote='Send photos or a brochure'
        alt={'evidence':quote,'requests':[
            {'topic':'materials','polarity':'request','subject':subject,
             'evidence':quote,'target':None} for subject in ('photos','brochure')]}
        value=packet(text=text,requests=[information('financing','explain financing options')],
                     alternatives=[alt])
        contract,_=compile_input(json.dumps(value),text)
        self.assertEqual(len(contract.alternatives),1)
        self.assertEqual(len(contract.alternatives[0].request_ids),2)
        self.assertEqual(len(contract.all_of),1)
        self.assertTrue(contract.permits('financing'))
        self.assertTrue(contract.permits('materials','photos'))
        contract.check_evidence(text)

    def test_legacy_v2_comparison_packet_still_accepted(self):
        text='Compare Cedar Studio and Cedar Loft.'
        legacy=packet(text=text)
        legacy.pop('comparison')
        legacy['version']=VERSION
        legacy['requests']=[{'topic':'comparison','polarity':'request',
                             'evidence':text,'members':[target('Cedar Studio'),target('Cedar Loft')],
                             'criteria':['general']}]
        old=Input.model_validate(legacy).model_dump(mode='json')
        contract,_=compile_input(json.dumps(old),text)
        self.assertEqual(len(contract.comparison.reference_ids),2)
        self.assertEqual(contract.version,'sales-understanding/1.0')
        contract.check_evidence(text)

    def test_v3_does_not_create_visit_consent_from_financing(self):
        text='I want to speak with a human. What financing options do you offer?'
        value=packet(text=text,requests=[information('human','I want to speak with a human.'),
                                               information('financing','What financing options do you offer?')])
        result,_=compile_input(json.dumps(value),text)
        self.assertIsNone(result.visit)
        self.assertTrue(result.permits('human'))
        self.assertTrue(result.permits('financing'))
        self.assertFalse(result.permits('appointment'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
