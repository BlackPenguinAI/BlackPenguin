"""Offline P1-A mixed price read checks: no model, DB or external effects.
Run in the deployed API container:
    python -m tools.sales_ai.p1a_mixed_price_read_selftest
"""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from app.modules.sales_agent.mixed_human_pricing import verified_mixed_price_read

MESSAGE='I want to speak to a human. What is the price of Bay Residence?'
QUESTION='What is the price of Bay Residence?'
COMMERCIAL={'property_types':[{'id':'synthetic-bay','property_type':'Bay Residence'}]}


def frame(message=MESSAGE, question=QUESTION, *, topic='pricing', property_name='Bay Residence',
          extra_requests=(), **overrides):
    req=NS(topic=NS(value=topic),polarity='request',evidence=question,reference_id='ref0')
    ref=NS(id='ref0',kind='property',expression=property_name,evidence=question)
    data=dict(requires_clarification=False,requests=[req,*extra_requests],references=[ref],
              visit=None,comparison=None,constraints=[],alternatives=[],releases=[],
              reschedule=None,cancellation=None,wait=None,moderation=None,
              appointment_query=None,personal_facts=[],preference_withdrawals=[],
              source_purposes=[],objections=[],confidence=0.0)
    data.update(overrides)
    return NS(**data)


class TestVerifiedMixedPriceRead(unittest.TestCase):
    def check(self,value=None,text=MESSAGE,commercial=COMMERCIAL,step='ask',holds=()):
        return verified_mixed_price_read(value if value is not None else frame(),text,commercial,
                                         human_step=step,holds=holds)

    def test_recorded_failure_is_read_only_even_with_zero_confidence(self):
        value=frame()
        self.assertTrue(self.check(value))
        self.assertEqual(value.confidence,0.0)
        self.assertFalse(value.requires_clarification)
        self.assertIsNone(value.visit)

    def test_contact_must_be_current_own_literal(self):
        for text in ('My friend said: '+MESSAGE,'If I want to speak to a human. '+QUESTION,
                     'I do not want to speak to a human. '+QUESTION,
                     '"'+MESSAGE+'"', 'I want to speak to a human. Please book a visit. '+QUESTION):
            with self.subTest(text=text):self.assertFalse(self.check(text=text))

    def test_no_human_step_or_recorded_step(self):
        for step in (None,'record','withdraw'):
            with self.subTest(step=step):self.assertFalse(self.check(step=step))

    def test_unapproved_or_ambiguous_property_refused(self):
        self.assertFalse(self.check(commercial={'property_types':[]}))
        self.assertFalse(self.check(commercial={'property_types':COMMERCIAL['property_types']*2}))
        self.assertFalse(self.check(commercial={'property_types':[{'property_type':'Bay Residence'}]}))
        self.assertFalse(self.check(frame(property_name='Cedar Studio')))

    def test_invented_reference_or_wrong_topic_refused(self):
        self.assertFalse(self.check(frame(topic='appointment')))
        self.assertFalse(self.check(frame(question='I want to speak to a human.')))
        self.assertFalse(self.check(frame(references=[NS(id='ref0',kind='unit',expression='Bay Residence',evidence=QUESTION)])))
        self.assertFalse(self.check(frame(requests=[])))

    def test_mixed_and_prohibited_requests_refused(self):
        self.assertFalse(self.check(frame(extra_requests=(NS(topic=NS(value='appointment'),polarity='request'),))))
        self.assertFalse(self.check(frame(visit=NS(action='request'))))
        self.assertFalse(self.check(frame(constraints=[NS(topic=NS(value='pricing'))])))
        self.assertFalse(self.check(holds={'pricing'}))
        self.assertFalse(self.check(frame(requires_clarification=True)))

    def test_still_no_model_confidence_promotion(self):
        obj=frame()
        before=vars(obj).copy()
        self.assertTrue(self.check(obj))
        self.assertEqual(before,vars(obj))

    def test_wiring_preserves_clarification_guard_and_audit(self):
        source=Path(__file__).resolve().parents[2]/'app/modules/sales_agent/active_service.py'
        content=source.read_text(encoding='utf-8')
        self.assertIn('pricing_read=bool(',content)
        self.assertIn('verified_mixed_price_read(u,inbound.content,commercial,',content)
        self.assertIn("'basis':'literal_scoped_mixed_human_price'",content)
        self.assertIn('or material_read or pricing_read or confirmation_ready',content)
        self.assertIn('if material_read or pricing_read or contextual_needs_read',content)


if __name__=='__main__':
    unittest.main(verbosity=2)
