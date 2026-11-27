"""Host-side contract checks; full-source compilation and Docker are CI gates."""
import ast
from pathlib import Path
import unittest

from continuous_overlay import CHANGES, CORE, SALES, GATEWAY, git_blob, transform
from continuous_entrypoint import allowed_control, PREFIX
from continuous_scope import CURRENT, CONTINUOUS, MODEL_KEY
from live_scope_policy import Capability
from startup_evidence import collect_events, PREFIX as EVENT_PREFIX


class NativeOverlayTests(unittest.TestCase):
    def test_exact_blob_digest(self):
        self.assertEqual(git_blob(b'hello\n'),'ce013625030ba8dba906f756967f9e9ca394464a')

    def test_uncertified_file_rejected(self):
        with self.assertRaisesRegex(ValueError,'Uncertified blob'):
            transform(CORE+'engine_selection.py',b'print(1)\n')

    def test_wrong_source_anchor_rejected(self):
        sample=b'def gate():\n    pass\n'
        with self.assertRaisesRegex(ValueError,'Unexpected source anchor'):
            transform(CORE+'engine_selection.py',sample,expected=git_blob(sample))

    def test_duplicate_anchor_rejected(self):
        anchor=CHANGES[CORE+'engine_selection.py'][1][0][0]
        source=('def f():\n    if True:\n'+anchor+'\n'+anchor+'\n').encode()
        with self.assertRaisesRegex(ValueError,'Unexpected source anchor'):
            transform(CORE+'engine_selection.py',source,expected=git_blob(source))

    def test_native_gate_transform_preserves_global_readiness(self):
        source=b"def live_hermes_ready():\n    return False\n\ndef require_selectable(engine):\n    if engine == 'hermes' and not live_hermes_ready():\n        raise EngineUnavailable('Hermes live routing is not certified in HEI-01A.')\n"
        result=transform(CORE+'engine_selection.py',source,expected=git_blob(source)).decode()
        tree=ast.parse(result)
        self.assertEqual(ast.unparse(tree.body[0]),'def live_hermes_ready():\n    return False')
        self.assertIn('from continuous_scope import gate',result)
        self.assertNotIn('mock.patch',result)

    def test_worker_uses_existing_route_and_disables_scheduled_lanes(self):
        edits=CHANGES[SALES+'live_worker.py'][1]
        self.assertIn("with bind_job(job_id, role='api')",edits[0][1])
        self.assertIn('await route_live_job(job_id, inbound=True',edits[0][1])
        self.assertIn('legacy_handler=deny_legacy',edits[0][1])
        self.assertIn('continue',edits[-1][1])

    def test_provider_transport_is_explicitly_simulated(self):
        edits=CHANGES[GATEWAY][1]
        self.assertIn('return await simulated_sms',edits[0][1])
        self.assertIn('raise PermissionError',edits[1][1])

    def test_staging_module_has_no_runtime_monkeypatch(self):
        base=Path(__file__).resolve().parent
        for name in ('continuous_scope.py','continuous_entrypoint.py'):
            tree=ast.parse((base/name).read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom):self.assertNotIn('unittest.mock',n.module or '')
                if isinstance(n,ast.Import):self.assertFalse(any(x.name=='unittest.mock' for x in n.names))

    def test_only_certified_modules_modified_in_images(self):
        self.assertEqual(len(CHANGES),10)
        for name,(sha,edits) in CHANGES.items():
            self.assertTrue(name.startswith('app/'))
            self.assertRegex(sha,r'^[0-9a-f]{40}$')
            self.assertTrue(edits)

    def test_runtime_overlay_compiles_exact_repository_sources_if_present(self):
        root=Path(__file__).resolve().parents[3]/'backend'
        if not (root/'app').is_dir():self.skipTest('Full certified repo is only present in CI')
        for name in CHANGES:
            output=transform(name,(root/name).read_bytes())
            compile(output,name,'exec')


class ControlTests(unittest.TestCase):
    def test_fixed_ingress(self):
        for case in ('first','second','revoked'):
            self.assertTrue(allowed_control('POST',PREFIX+'/enqueue/'+case))
            self.assertTrue(allowed_control('GET',PREFIX+'/job/'+case))

    def test_unknown_scope_and_wrong_method_denied(self):
        for method,path in [('POST',PREFIX+'/enqueue/other'),('PUT',PREFIX+'/grant'),('GET',PREFIX+'/enqueue/first'),('POST','/api/v1/webhooks/telnyx/messaging'),('POST',PREFIX+'/enqueue/first/extra')]:
            self.assertFalse(allowed_control(method,path))

    def test_revocation_and_replay_routes_are_post_only(self):
        for name in ('grant','revoke','replay'):
            self.assertTrue(allowed_control('POST',PREFIX+'/'+name))
            self.assertFalse(allowed_control('GET',PREFIX+'/'+name))

    def test_capability_default_closed_and_context_isolated(self):
        self.assertIsNone(CURRENT.get())
        cap=Capability('first','gen','policy')
        token=CURRENT.set(cap)
        try:self.assertEqual(CURRENT.get(),cap)
        finally:CURRENT.reset(token)
        self.assertIsNone(CURRENT.get())

    def test_sanitized_continuous_failure(self):
        raw=EVENT_PREFIX+'{"phase":"continuous_worker","status":"FAIL","exception_type":"PermissionError","message":"secret","locations":[{"file":"live_job.py","line":99}]}'
        self.assertEqual(collect_events(raw),[{'phase':'continuous_worker','status':'FAIL','exception_type':'PermissionError','locations':[{'file':'live_job.py','line':99}]}])

    def test_key_separate_from_openrouter_default(self):
        self.assertNotEqual(MODEL_KEY,'OPENROUTER_API_KEY')
        self.assertEqual(CONTINUOUS,'hei06a2b3-native-staging-v1')


if __name__=='__main__':unittest.main()
