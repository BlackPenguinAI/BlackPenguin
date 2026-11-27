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


class BootstrapRegressionTests(unittest.TestCase):
    @staticmethod
    def unresolved_globals(source, filename):
        # CPython's scope analysis understands nested functions, comprehensions,
        # imports and closures. This deliberately checks only unresolved globals,
        # not definite assignment or dynamic imports; no extra CI dependency.
        import builtins
        import symtable
        table = symtable.symtable(source, filename, 'exec')
        defined = {symbol.get_name() for symbol in table.get_symbols()
                   if symbol.is_imported() or symbol.is_assigned() or symbol.is_namespace()}
        defined |= set(dir(builtins)) | {
            '__name__', '__file__', '__package__', '__doc__', '__spec__',
            '__loader__', '__cached__', '__annotations__',
        }
        def walk(scope):
            found = [(scope.get_name(), symbol.get_name())
                     for symbol in scope.get_symbols()
                     if symbol.is_global() and symbol.is_referenced()
                     and symbol.get_name() not in defined]
            for child in scope.get_children():
                found.extend(walk(child))
            return found
        return walk(table)

    def test_missing_global_checker_detects_original_defect(self):
        source = ('from datetime import datetime, timezone\n'
                  'def seed():\n'
                  '    return datetime.now(timezone.utc)-timedelta(seconds=2)\n')
        self.assertEqual(self.unresolved_globals(source, 'old_seed.py'),
                         [('seed', 'timedelta')])

    def test_continuous_modules_have_no_unresolved_globals(self):
        base = Path(__file__).resolve().parent
        for path in sorted(base.glob('continuous_*.py')):
            with self.subTest(file=path.name):
                self.assertEqual(self.unresolved_globals(path.read_text(), str(path)), [])

    def test_seed_creates_fresh_inventory_and_grant(self):
        # Exercise the actual seed body with DB/ORM doubles. No PostgreSQL,
        # network or provider credentials are required for this regression.
        from datetime import datetime, timezone, timedelta
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import MagicMock, patch
        import continuous_scope as scope

        def model(name):
            return type(name, (SimpleNamespace,), {})

        modules = {}
        for module_name, names in {
            'app.modules.companies.models': ('Company',),
            'app.modules.projects.models': ('Project', 'ProjectProfile', 'ProjectPropertyType'),
            'app.modules.sales_crm.models': ('Lead', 'Meeting'),
            'app.modules.sales_agent.models': ('SalesConversation', 'SalesInboundJob', 'OutboundMessage', 'SalesFollowUpJob'),
        }.items():
            module = ModuleType(module_name)
            for name in names:
                setattr(module, name, model(name))
            modules[module_name] = module
        engine = MagicMock()
        conn = engine.begin.return_value.__enter__.return_value
        db = MagicMock()
        db.query.return_value.count.return_value = 0
        db.get.return_value = None
        session = MagicMock()
        session.return_value.__enter__.return_value = db
        orm = ModuleType('sqlalchemy.orm')
        orm.Session = session
        modules['sqlalchemy.orm'] = orm
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        with patch.dict(sys.modules, modules), \
             patch.object(scope, 'attest'), \
             patch.object(scope, 'sql') as sql, \
             patch.object(scope, 'current_grant', return_value=None), \
             patch.object(scope, 'published', return_value='policy-test'), \
             patch.object(scope, 'checked_scope'):
            result = scope.seed(engine, None)
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        self.assertEqual(result, {'initialized': True, 'grant_active': True, 'policy_id': 'policy-test'})
        session.assert_called_once_with(bind=conn, join_transaction_mode='rollback_only')
        inventory = [call.args[0] for call in db.add.call_args_list
                     if isinstance(call.args[0], modules['app.modules.projects.models'].ProjectPropertyType)]
        self.assertEqual([item.name for item in inventory], ['Van Buren', 'Oakwood'])
        self.assertEqual(inventory[0].inventory_updated_at, inventory[1].inventory_updated_at)
        for item in inventory:
            self.assertIsNone(item.inventory_updated_at.tzinfo)
            self.assertLessEqual(before-timedelta(seconds=2), item.inventory_updated_at)
            self.assertLessEqual(item.inventory_updated_at, after-timedelta(seconds=2))
        grants = [call for call in sql.call_args_list if 'INSERT INTO hei06a2_live_grant' in call.args[1]]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0].kwargs['policy'], 'policy-test')
        db.commit.assert_called_once()


if __name__=='__main__':unittest.main()
