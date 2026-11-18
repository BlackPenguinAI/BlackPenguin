"""P1-C.1 pure/offline regression and real scoped resolver tests; no model calls."""
import unittest
from types import SimpleNamespace as NS
from app.modules.sales_agent.financing_read import verified_financing_policy_read
from app.modules.sales_agent.understanding_contract import Understanding
from app.modules.sales_agent.reference_resolution import (
    scoped_compound_property, Resolver,
)


def parsed(text, *, confidence=0.0, visiting=False, extras=()):
    row=dict(id='finance',topic='financing',subject=None,polarity='request',
             evidence='What financing options do you offer?',reference_id=None)
    data=dict(version='sales-understanding/1.0',requests=[row,*extras],
        all_of=['finance',*[e['id'] for e in extras]],alternatives=[],
        constraints=[],references=[],preferences=[],requires_clarification=False,
        clarification_question=None,confidence=confidence)
    if visiting:
        data['visit']=dict(action='decline',evidence='I do not want a visit yet',timing=None)
        data['constraints']=[dict(topic='appointment',subject=None,effect='prohibit',
             scope='until_explicit_change',evidence='I do not want a visit yet')]
    return Understanding.model_validate(data)


class TestFinancingRead(unittest.TestCase):
    def test_pure_financing_policy_read_even_when_model_confidence_is_zero(self):
        text='What financing options do you offer?'
        self.assertTrue(verified_financing_policy_read(parsed(text),text))
        self.assertEqual(parsed(text).confidence,0.0)

    def test_visit_refusal_and_independent_policy_question(self):
        text='I do not want a visit yet. What financing options do you offer?'
        self.assertTrue(verified_financing_policy_read(parsed(text,visiting=True),text))

    def test_no_bypass_when_policy_holds_financing(self):
        text='What financing options do you offer?'
        self.assertFalse(verified_financing_policy_read(parsed(text),text,holds={'financing'}))

    def test_nonliteral_or_untrusted_questions_fail_closed(self):
        value=parsed('What financing options do you offer?')
        for text in ('My friend said: What financing options do you offer?',
                     'If I buy, what financing options do you offer?',
                     'My budget is 900,000 USD, paying cash.',
                     'What financing options do you offer? Please book a visit.',
                     'What financing options do you offer? Or send photos?'):
            with self.subTest(text=text):
                self.assertFalse(verified_financing_policy_read(value,text))

    def test_user_clarification_or_mixed_request_not_overridden(self):
        text='What financing options do you offer?'
        u=parsed(text).model_copy(update={'requires_clarification':True,
                         'clarification_question':'Which property?'})
        self.assertFalse(verified_financing_policy_read(u,text))
        u=parsed(text,extras=[dict(id='other',topic='materials',subject='photos',
                                  polarity='request',evidence='photos',reference_id=None)])
        self.assertFalse(verified_financing_policy_read(u,text))

    def test_no_financing_bypass_for_write_or_optout(self):
        text='What financing options do you offer?'
        for field,value in [('visit',NS(action='request')),
                            ('wait',NS(action='request')),
                            ('cancellation',NS(action='request')),
                            ('reschedule',NS(action='request'))]:
            u=parsed(text).model_copy(update={field:value})
            with self.subTest(field=field):
                self.assertFalse(verified_financing_policy_read(u,text))


class TestScopedCompoundProperty(unittest.TestCase):
    def test_exact_approved_project_name(self):
        self.assertEqual(scoped_compound_property('Bay Residence at Harbor Gardens',
                         'Harbor Gardens'), 'bay residence')

    def test_synthetic_demo_prefix_is_not_a_production_alias(self):
        text='Bay Residence at Harbor Gardens'
        self.assertEqual(scoped_compound_property(text,'SYNTHETIC Harbor Gardens',demo=True),
                         'bay residence')
        self.assertIsNone(scoped_compound_property(text,'SYNTHETIC Harbor Gardens',demo=False))

    def test_foreign_project_unknown_owner_and_untrusted_names_fail(self):
        for phrase in ('Bay Residence at Other Project','Other Residence at Harbor Gardens',
                       'Bay Residence or Loft at Harbor Gardens'):
            canonical=scoped_compound_property(phrase,'Harbor Gardens')
            if 'at Harbor Gardens' not in phrase:
                self.assertIsNone(canonical)
            else:
                self.assertNotEqual(canonical,'bay residence')

    def test_real_resolver_only_binds_one_scoped_property(self):
        class DB:
            def get(self,model,identifier):
                return NS(name='SYNTHETIC Harbor Gardens',is_demo=True)
        resolver=object.__new__(Resolver)
        resolver.db=DB()
        resolver.scope=NS(project_id='project')
        resolver.types={'one':{'property_type':'Bay Residence'}}
        resolver.units={}
        resolver.state=NS(offers=[],selected_property_type_id=None,selected_unit_id=None)
        result=resolver.resolve(NS(kind='property',expression='Bay Residence at Harbor Gardens'))
        self.assertEqual(result['status'],'resolved')
        self.assertEqual(result['value']['property_id'],'one')
        resolver.types['two']={'property_type':'Bay Residence'}
        result=resolver.resolve(NS(kind='property',expression='Bay Residence at Harbor Gardens'))
        self.assertNotEqual(result['status'],'resolved')


if __name__=='__main__':
    unittest.main(verbosity=2)
