"""Pure offline P2-B audit guard tests; no database, LLM or network needed."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from .p2b_repair_audit import audit, read_report, run_metrics
from .p2b_repair_ablation import decode_samples, noop, STAGES


def synthetic_bundle(path, *, raw='secret lead answer', repeats=1, truncated=False):
    # The evidence is deliberately fake/synthetic and must never be copied
    # into any aggregate report.
    import hashlib
    attempt={'outcome':'accepted','raw_response':raw,'raw_response_sha256':hashlib.sha256(raw.encode()).hexdigest(),
             'raw_response_truncated':truncated,
             'normalizations':[{'field':'visit','action':'omit_human_contact_misread_as_visit',
                                'evidence':'DO_NOT_LEAK_THIS_QUOTE'}]}
    turns=[{'turn':i+1,'lead_message':'DO_NOT_LEAK_THIS_LEAD',
            'reply':'DO_NOT_LEAK_THIS_REPLY',
            'interpretation_attempts':[attempt],
            'input_trace':{'observation_loop':{'status':'PASS'}}}
            for i in range(repeats)]
    report={'synthetic_only':True,'version':'synthetic-test','commit':'a'*40,
            'configuration_sha256':'b'*64,'sales_model':'test/offline',
            'cases':[{'case':'test','turns':turns}],
            'scenario_count':1,'summary':{'PASS':6,'FAIL':0,'BLOCKED':0},
            'provider_calls':1,'provider_usage':{'prompt_tokens':1,'completion_tokens':1,'cost_usd':0.0}}
    with ZipFile(path,'w') as z:
        z.writestr('report.json',json.dumps(report))
    return path


class TestRepairAudit(unittest.TestCase):
    def test_counts_stage_and_protects_private_raw_input(self):
        with tempfile.TemporaryDirectory() as d:
            path=synthetic_bundle(Path(d)/'evidence.zip')
            value=audit([path])
            self.assertEqual(value['turn_count'],1)
            self.assertEqual(value['repair_actions']['omit_human_contact_misread_as_visit'],1)
            self.assertEqual(value['repair_stages']['mixed_human_visit.omit_spurious_visit'],1)
            self.assertEqual(value['decision'],'NO_AUTOMATIC_REMOVAL')
            output=json.dumps(value)
            for secret in ('DO_NOT_LEAK_THIS_QUOTE','DO_NOT_LEAK_THIS_LEAD',
                           'DO_NOT_LEAK_THIS_REPLY','secret lead answer'):
                self.assertNotIn(secret,output)

    def test_truncated_response_does_not_get_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            path=synthetic_bundle(Path(d)/'evidence.zip',truncated=True)
            assert read_report(path)['synthetic_only']
            samples,skips=decode_samples([path],max_packets=1)
            self.assertEqual(len(samples),0)
            self.assertEqual(skips,{'missing_or_truncated_packet':1})

    def test_unknown_untrusted_action_is_never_echoed(self):
        report={'synthetic_only':True,'cases':[{'turns':[{'interpretation_attempts':[
            {'normalizations':[{'action':'RAW_CLIENT_PII'}]}]}]}]}
        value=run_metrics(report,label='run_1')
        self.assertIn('unrecognized_action',value['repair_actions'])
        self.assertNotIn('RAW_CLIENT_PII',json.dumps(value))

    def test_missing_or_nonsynthetic_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'wrong.zip'
            with ZipFile(path,'w') as z:z.writestr('report.json',json.dumps({'synthetic_only':False,'cases':[]}))
            with self.assertRaises(ValueError):read_report(path)

    def test_full_closing_suite_does_not_pass_without_verified_reads(self):
        names=('decline_visit_questions','human_then_question','human_insists',
               'human_record_then_question','human_withdrawal','farewell_then_reopen',
               'unavailable_then_close','mixed_human_price')
        cases=[]
        for name in names:
            content='I do not want a visit yet. What financing options do you offer?' if name=='decline_visit_questions' else ('What financing options do you offer?' if name in ('human_then_question','human_record_then_question','farewell_then_reopen') else 'I want to speak to a human')
            cases.append({'case':name,'turns':[{'turn':1,'lead_message':content,
                          'understanding':{'requires_clarification':False},
                          'input_trace':{'observation_loop':{'status':'PASS','tools':[],'observations':[]}}}]})
        value=run_metrics({'cases':cases,'scenario_count':8,
                           'summary':{'PASS':404,'FAIL':0,'BLOCKED':0}},label='run_1')
        self.assertEqual(value['focused_functional_gate'],'BLOCKED_FOCUSED')
        self.assertEqual(value['financing_reads_verified'],0)
        self.assertEqual(value['visit_availability_verified'],0)

    def test_noop_has_no_external_effects(self):
        payload={'topic':'catalog'}
        self.assertEqual(noop(payload,'message'),(payload,[]))
        self.assertTrue(len(STAGES)>=8)

    def test_no_stage_is_preapproved_for_removal(self):
        from .p2b_repair_audit import PROTECTED_STAGES
        self.assertTrue(PROTECTED_STAGES)
        self.assertEqual(audit([self._one()])['decision'],'NO_AUTOMATIC_REMOVAL')

    def _one(self):
        # Needed only for one test; temporary files are not retained externally.
        if not hasattr(self,'_temp'):
            self._temp=tempfile.TemporaryDirectory()
            self.addCleanup(self._temp.cleanup)
        return synthetic_bundle(Path(self._temp.name)/'evidence.zip')


if __name__=='__main__':unittest.main(verbosity=2)
