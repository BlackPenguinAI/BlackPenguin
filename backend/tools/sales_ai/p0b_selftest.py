"""P0-B synthetic/offline tests. Never touches a production DB or LLM.

Run inside the deployed container:
  python -m tools.sales_ai.p0b_selftest
"""
import unittest
from datetime import datetime, timedelta, timezone
from app.modules.sales_agent.booking_intent import canonicalize_new_visit
from app.modules.sales_agent.booking_fastpath import qualifies, deterministic_audit_metadata, VERSION
from app.modules.sales_agent.turn_configuration import digest

SYNTHETIC = ('I am interested in Bay Residence at Harbor Gardens and would like '
             'to book an in-person visit. My budget is 900,000 USD, paying cash. '
             'Any time in the next seven days works; please use the project timezone.')
VISIT = 'would like to book an in-person visit'
NAMES = ['Bay Residence', 'Cedar Studio', 'Hill Loft']


def simulated_wire(message=SYNTHETIC, visit=VISIT, comparison=True):
    entries = ([{'topic': 'comparison', 'polarity': 'request',
                 'evidence': message, 'members': [
                     {'kind': 'property', 'expression': name, 'evidence': name}
                     for name in NAMES],
                 'include_current': False, 'include_all': False,
                 'all_kind': 'property', 'criteria': ['general'],
                 'feature': None, 'operation': 'compare'}] if comparison else [])
    return {
        'version': 'sales-interpretation-input/2.0',
        'requests': entries, 'visit': {'action': 'request', 'evidence': visit,
                                       'timing': None},
        'preferences': [
            {'key': 'budget', 'value': '900000 USD', 'evidence': '900,000 USD',
             'status': 'declared'},
            {'key': 'financing', 'value': 'cash', 'evidence': 'paying cash',
             'status': 'declared'},
        ],
        'requires_clarification': False, 'constraints': [], 'releases': [],
        'alternatives': [], 'cancellation': None, 'reschedule': None,
        'wait': None, 'moderation': None, 'appointment_query': None,
        'selection': None,
    }


class TestSyntheticBookingWire(unittest.TestCase):
    def test_mixed_visit_drops_historical_comparison(self):
        result, notes = canonicalize_new_visit(simulated_wire(), SYNTHETIC, NAMES)
        self.assertEqual([r['topic'] for r in result['requests']], ['appointment'])
        self.assertTrue(notes)
        self.assertEqual(result['requests'][0]['target']['expression'], 'Bay Residence')
        self.assertEqual(result['requests'][0]['target']['evidence'], 'Bay Residence')
        self.assertEqual({p['key'] for p in result['preferences']}, {'financing', 'budget'})
        self.assertEqual(result['visit']['action'], 'request')

    def test_no_invented_booking_confirmation(self):
        item=simulated_wire(message='Yes', visit='Yes')
        result, notes=canonicalize_new_visit(item,'Yes',NAMES)
        self.assertEqual(result,item)
        self.assertEqual(notes,[])

    def test_reject_historical_only_visit_evidence(self):
        item=simulated_wire(message='What is the price?',visit=VISIT)
        result, notes=canonicalize_new_visit(item,'What is the price?',NAMES)
        self.assertEqual((result,notes),(item,[]))

    def test_genuine_comparison_preserved(self):
        message=SYNTHETIC+' Also, compare Bay Residence and Cedar Studio.'
        item=simulated_wire(message=message)
        result,notes=canonicalize_new_visit(item,message,NAMES)
        self.assertEqual((result,notes),(item,[]))

    def test_conditional_visit_does_not_grant_intent(self):
        message='If I would like to book an in-person visit, what happens?'
        item=simulated_wire(message=message)
        result,notes=canonicalize_new_visit(item,message,NAMES)
        self.assertEqual((result,notes),(item,[]))

    def test_restrictions_are_not_rewritten(self):
        item=simulated_wire()
        item['constraints']=[{'topic':'appointment','effect':'prohibit'}]
        result,notes=canonicalize_new_visit(item,SYNTHETIC,NAMES)
        self.assertEqual((result,notes),(item,[]))

    def test_ambiguous_owner_not_guessed(self):
        result, notes = canonicalize_new_visit(simulated_wire(),SYNTHETIC,
                                               ['Bay Residence','Harbor Gardens'])
        self.assertTrue(notes)
        self.assertIsNone(result['requests'][0]['target'])

    def test_independent_financing_request_preserved(self):
        item=simulated_wire()
        item['requests'].append({'topic':'financing','subject':None,
                                 'polarity':'request','evidence':'paying cash','target':None})
        result,_=canonicalize_new_visit(item,SYNTHETIC,NAMES)
        self.assertEqual({r['topic'] for r in result['requests']},{'appointment','financing'})


class TestSyntheticBookingAcceptance(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,15,0,tzinfo=timezone.utc)
        self.scope=dict(company_id='company-synthetic',project_id='project-synthetic',
                        conversation_id='chat-synthetic',lead_id='lead-synthetic')
        self.proposal=dict(scope=self.scope,option={'starts_at':'2026-11-19T15:00:00+00:00'},
                           context={'property_type_id':'fake-property'},
                           preferences={'duration_minutes':45},
                           expires_at=(self.now+timedelta(minutes=20)).isoformat())
        self.proposal['id']=digest(self.proposal)
        self.metadata={'booking_confirmation':{'id':self.proposal['id'],
                         'expires_at':self.proposal['expires_at']}}

    def check(self, **changes):
        arguments=dict(plain_assent=True,proposal=self.proposal,
                       metadata=self.metadata,scope=self.scope,accepted=True,
                       now=self.now,digest_fn=digest,action_holds=())
        arguments.update(changes)
        return qualifies(**arguments)

    def test_deterministic_audit_does_not_claim_llm_prompt(self):
        metadata=deterministic_audit_metadata('synthetic-inbound',7)
        self.assertEqual(metadata['inbound_message_id'],'synthetic-inbound')
        self.assertEqual(metadata['expected_revision'],7)
        self.assertEqual(metadata['inference_mode'],'deterministic')
        self.assertEqual(metadata['input_contract'],VERSION)
        self.assertEqual(metadata['interpretation_attempts'],[])
        self.assertEqual(metadata['prompt_snapshot'],{
            'version':VERSION,'model_invoked':False,'system':None,
        })
        self.assertNotIn('input_system_version',metadata['prompt_snapshot'])

    def test_valid_delivered_exact_confirmation(self):
        self.assertTrue(self.check())

    def test_pending_or_undelivered_rejected(self):
        self.assertFalse(self.check(accepted=False))

    def test_no_expired_confirmation(self):
        self.assertFalse(self.check(now=self.now+timedelta(hours=1)))

    def test_no_changed_proposal(self):
        proposal={**self.proposal,'preferences':{'duration_minutes':60}}
        self.assertFalse(self.check(proposal=proposal))

    def test_no_foreign_lead(self):
        self.assertFalse(self.check(scope={**self.scope,'lead_id':'another-lead'}))

    def test_no_competing_offers(self):
        self.assertFalse(self.check(metadata={**self.metadata,'material_offer':{'asset_ids':['file']}}))

    def test_no_ambiguous_yes(self):
        self.assertFalse(self.check(plain_assent=False))

    def test_permission_hold(self):
        self.assertFalse(self.check(action_holds={'appointment'}))

    def test_offer_mismatch(self):
        self.assertFalse(self.check(metadata={'booking_confirmation':{'id':'other'}}))


if __name__=='__main__':
    unittest.main(verbosity=2)
