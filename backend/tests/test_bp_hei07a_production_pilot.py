"""HEI-07A isolated authorization/routing tests; no provider or DB calls."""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock, patch
from uuid import UUID

from app.modules.hermes_sales_core import production_release as release
from app.modules.hermes_sales_core import engine_selection as selection
from app.modules.sales_agent import engine_router as router


def uid(n):
    return str(UUID(int=n))


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(zip(release.FIELDS, map(uid, range(1, 5))))
        self.other = {**self.scope, 'lead_id': uid(9)}
        self.phone = '+12025550101'
        self.status = {'active_sales_engine': 'hermes', 'published_version_id': 'p1'}
        self.env = {'ENVIRONMENT': 'production', 'HERMES_RELEASE_MODE': 'pilot',
                    'APP_COMMIT_SHA': 'a'*40, 'HERMES_RELEASE_SHA': 'a'*40,
                    'HERMES_RUNTIME_ROLE': 'api', 'HERMES_INTERNAL_TOKEN': 'b'*64,
                    'HERMES_PILOT_SCOPES': json.dumps([{**self.scope,'test_phone': self.phone}]),
                    'HERMES_PILOT_UNTIL': (datetime.now(timezone.utc)+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}
        p = patch.dict(os.environ, self.env, clear=True)
        p.start(); self.addCleanup(p.stop)
        release._health_cache = (None,0,False)

    def test_default_closed(self):
        os.environ.pop('HERMES_RELEASE_MODE')
        self.assertFalse(selection.live_hermes_ready())
        self.assertEqual(selection.routing_status(None)['available_engines'], ['langgraph'])

    def test_staging_cannot_open(self):
        os.environ['ENVIRONMENT']='staging'
        self.assertFalse(release.ready())

    def test_global_not_supported(self):
        os.environ['HERMES_RELEASE_MODE']='global'
        self.assertFalse(release.ready())

    def test_bad_revision(self):
        os.environ['HERMES_RELEASE_SHA']='c'*40
        self.assertIsNone(release.configuration())

    def test_bad_token(self):
        os.environ['HERMES_INTERNAL_TOKEN']='short'
        self.assertIsNone(release.configuration())

    def test_duplicate_scope(self):
        rows=json.loads(self.env['HERMES_PILOT_SCOPES']);os.environ['HERMES_PILOT_SCOPES']=json.dumps(rows*2)
        self.assertIsNone(release.configuration())

    def test_expired(self):
        os.environ['HERMES_PILOT_UNTIL']='2000-01-01T00:00:00Z'
        self.assertFalse(release.ready())
        with self.assertRaises(selection.EngineUnavailable):
            with release.bind_scope(self.scope): pass

    def test_max_expiry(self):
        os.environ['HERMES_PILOT_UNTIL']='2099-01-01T00:00:00Z'
        self.assertIsNone(release.configuration())

    def test_scope_exact(self):
        self.assertTrue(release.allowed(self.scope)); self.assertFalse(release.allowed(self.other))
        self.assertFalse(release.allowed({'lead_id':self.scope['lead_id']}))

    def test_nested_scope_denied_and_reset(self):
        with release.bind_scope(self.scope):
            release.require_execution()
            with self.assertRaises(selection.EngineUnavailable): release.assert_bound_scope(self.other)
        with self.assertRaises(selection.EngineUnavailable): release.require_execution()

    def test_admin_only_api(self):
        with release.admin_selection(): release.require_execution()
        with self.assertRaises(selection.EngineUnavailable): release.require_execution()
        os.environ['HERMES_RUNTIME_ROLE']='sdk'
        with release.admin_selection():
            with self.assertRaises(selection.EngineUnavailable): release.require_execution()

    def test_nonpilot_explicit_legacy(self):
        with patch.object(selection,'live_hermes_ready',return_value=False):
            self.assertEqual(router.decide(scope=self.other,status=self.status)['engine'],'langgraph')

    def test_pinned_hermes_outside_denied(self):
        with self.assertRaises(selection.EngineUnavailable):
            router.decide(scope=self.other,status=self.status,pin={**self.other,'engine':'hermes','policy_version_id':'p1'})

    def test_pinned_legacy_preserved(self):
        self.assertEqual(router.decide(scope=self.scope,status=self.status,pin={**self.scope,'engine':'langgraph'})['engine'],'langgraph')

    def test_selected_legacy_preserved(self):
        self.assertEqual(router.decide(scope=self.scope,status={'active_sales_engine':'langgraph'})['engine'],'langgraph')

    def test_pilot_hermes_routes(self):
        with patch.object(selection,'live_hermes_ready',return_value=True):
            pin=router.decide(scope=self.scope,status=self.status)
        self.assertEqual((pin['engine'],pin['policy_version_id']),('hermes','p1'))

    def test_pilot_not_ready_no_fallback(self):
        with patch.object(selection,'live_hermes_ready',return_value=False):
            with self.assertRaises(selection.EngineUnavailable): router.decide(scope=self.scope,status=self.status)

    def test_authenticated_readiness_exact(self):
        cfg=release.configuration()
        import httpx
        with patch.object(httpx,'Client') as client:
            response=client.return_value.__enter__.return_value.get.return_value
            response.status_code=200; response.json.return_value={'status':'ready','release':cfg.revision,'scope_fingerprint':cfg.fingerprint,'mode':'pilot','transport':'private-sdk'}
            self.assertTrue(release.ready())
            client.return_value.__enter__.return_value.get.assert_called_once_with(release.READY_URL,headers={'Authorization':'Bearer '+'b'*64})
            release._health_cache=(None,0,False)
            response.json.return_value['release']='c'*40
            self.assertFalse(release.ready())

    def test_sdk_key_required(self):
        os.environ['HERMES_RUNTIME_ROLE']='sdk'
        self.assertFalse(release.ready())
        os.environ['OPENROUTER_API_KEY']='fixture-not-real'
        self.assertTrue(release.ready())

    def test_target_requires_test_flag_and_phone(self):
        lead=SimpleNamespace(id=self.scope['lead_id'],company_id=self.scope['company_id'],project_id=self.scope['project_id'],is_test=True,is_demo=False,deleted_at=None,phone=self.phone)
        conv=SimpleNamespace(**{k:v for k,v in self.scope.items() if k!='conversation_id'},id=self.scope['conversation_id'])
        db=MagicMock();db.query.return_value.filter_by.return_value.populate_existing.return_value.one_or_none.return_value=lead
        fake_lead=ModuleType('app.modules.sales_crm.models');fake_lead.Lead=object()
        fake_routes=ModuleType('app.modules.sales_agent.provider_routes');fake_routes.parts=lambda c:('+12025550100',self.phone)
        with patch.dict(sys.modules,{'app.modules.sales_crm.models':fake_lead,'app.modules.sales_agent.provider_routes':fake_routes}):
            self.assertIs(release.validate_target(db,conv),lead)
            lead.is_test=False
            with self.assertRaises(selection.EngineUnavailable):release.validate_target(db,conv)
            lead.is_test=True;lead.phone='+12025550109'
            with self.assertRaises(selection.EngineUnavailable):release.validate_target(db,conv)
            lead.phone=self.phone;fake_routes.parts=lambda c:('+12025550100','+12025550109')
            with self.assertRaises(selection.EngineUnavailable):release.validate_target(db,conv)


if __name__ == '__main__':
    unittest.main()
