"""Local stdlib tests for the fail-closed environment contract."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from guard import validate_environment, check_database, PURPOSE, DB_NAME


class EnvironmentContract(unittest.TestCase):
    def setUp(self):
        self.env = {
            'ENVIRONMENT':'test','HEI06A_PURPOSE':PURPOSE,'HEI06A_COMMIT':'a'*40,
            'HERMES_INTERNAL_TOKEN':'b'*64,'HEI06A_MODE':'offline',
            'DATABASE_URL':f'postgresql+psycopg2://{DB_NAME}:'+('c'*48)+f'@hei06a-postgres:5432/{DB_NAME}',
            'OPENROUTER_API_KEY':'test-only','META_ACCESS_TOKEN':'test-only',
        }

    def test_offline_worker(self):
        self.assertEqual(validate_environment(self.env),'offline')

    def test_offline_sdk(self):
        self.assertEqual(validate_environment(self.env,sdk=True),'offline')

    def test_model_sdk_requires_key(self):
        self.env['HEI06A_MODE']='model'
        with self.assertRaises(PermissionError):validate_environment(self.env,sdk=True)
        self.env['OPENROUTER_API_KEY']='example-not-a-real-key'
        self.assertEqual(validate_environment(self.env,sdk=True),'model')
        with self.assertRaises(PermissionError):validate_environment(self.env)

    def test_model_worker_has_no_key(self):
        self.env['HEI06A_MODE']='model'
        self.assertEqual(validate_environment(self.env),'model')

    def test_wrong_identity(self):
        for key,value in [('ENVIRONMENT','production'),('HEI06A_PURPOSE','wrong'),
                          ('HEI06A_COMMIT','a'*7),('HERMES_INTERNAL_TOKEN','test'),
                          ('HEI06A_MODE','production'),('META_ACCESS_TOKEN','secret'),
                          ('OPENROUTER_API_KEY','secret')]:
            with self.subTest(key=key),self.assertRaises(PermissionError):
                validate_environment({**self.env,key:value})

    def test_external_db_denied(self):
        for old,new in [('hei06a-postgres','localhost'),('5432','5433'),
                        ('/'+DB_NAME,'/blackpenguin_db'),(DB_NAME+':','postgres:'),
                        ('postgresql+psycopg2','sqlite'),('c'*48,'short')]:
            with self.subTest(old=old),self.assertRaises(PermissionError):
                validate_environment({**self.env,'DATABASE_URL':self.env['DATABASE_URL'].replace(old,new)})

    def test_query_and_fragment_denied(self):
        for suffix in ('?options=unsafe','#fragment'):
            with self.subTest(suffix=suffix),self.assertRaises(PermissionError):
                validate_environment({**self.env,'DATABASE_URL':self.env['DATABASE_URL']+suffix})

    def test_external_credentials_denied(self):
        for name in ('TELNYX_API_KEY','TELNYX_AUTH_TOKEN','TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN',
                     'GOOGLE_CALENDAR_CLIENT_ID','GOOGLE_CALENDAR_CLIENT_SECRET','GOOGLE_APPLICATION_CREDENTIALS',
                     'FIREBASE_ADMIN_BRIDGE_SECRET','SMTP_PASSWORD'):
            with self.subTest(name=name),self.assertRaises(PermissionError):
                validate_environment({**self.env,name:'test-not-allowed'})

    def test_missing_required_values_denied(self):
        for name in tuple(self.env):
            with self.subTest(name=name),self.assertRaises(PermissionError):
                validate_environment({k:v for k,v in self.env.items() if k!=name})


class DatabaseContract(unittest.TestCase):
    def connection(self, identity, markers):
        return SimpleNamespace(execute=lambda sql: (SimpleNamespace(one=lambda:identity)
            if sql.startswith('SELECT current_database') else
            SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:markers))))

    def test_valid_disposable_marker(self):
        with patch.dict('sys.modules', {'sqlalchemy':SimpleNamespace(text=lambda s:s)}):
            check_database(self.connection((DB_NAME,DB_NAME,'160008'),[PURPOSE]))

    def test_wrong_db_identity(self):
        with patch.dict('sys.modules', {'sqlalchemy':SimpleNamespace(text=lambda s:s)}):
            for identity in [('blackpenguin_db',DB_NAME,'160008'),(DB_NAME,'postgres','160008'),
                             (DB_NAME,DB_NAME,'170001')]:
                with self.subTest(identity=identity),self.assertRaises(PermissionError):
                    check_database(self.connection(identity,[PURPOSE]))

    def test_wrong_or_missing_marker(self):
        with patch.dict('sys.modules', {'sqlalchemy':SimpleNamespace(text=lambda s:s)}):
            for markers in ([],['other'],[PURPOSE,'other']):
                with self.subTest(markers=markers),self.assertRaises(PermissionError):
                    check_database(self.connection((DB_NAME,DB_NAME,'160008'),markers))


class WorkerBootstrapContract(unittest.TestCase):
    def test_registry_before_mapper_configuration(self):
        import worker_probe
        calls = []
        def load(name):
            calls.append(name)
            return SimpleNamespace(configure_mappers=lambda: calls.append('configure_mappers'))
        with patch.object(worker_probe, 'import_module', side_effect=load):
            worker_probe.register_orm()
        self.assertEqual(calls, ['app.db.base', 'sqlalchemy.orm', 'configure_mappers'])

    def test_mapper_error_keeps_type_and_no_private_text(self):
        import worker_probe
        import json
        error_class = type('InvalidRequestError', (Exception,), {})
        source = "raise error_class('PRIVATE_PASSWORD_AND_URL')"
        try:
            exec(compile(source, '/opt/staging/worker_probe.py', 'exec'), {'error_class':error_class})
        except error_class as exc:
            result = worker_probe.failure_evidence(exc)
        self.assertEqual(result, {'type':'InvalidRequestError',
                                  'locations':[{'file':'worker_probe.py','line':1}]})
        self.assertNotIn('PRIVATE_PASSWORD_AND_URL', json.dumps(result))

    def test_unknown_exception_does_not_expose_name_or_message(self):
        import worker_probe
        result = worker_probe.failure_evidence(type('PrivateClassName', (Exception,), {})('private'))
        self.assertEqual(result, {'type':'other_error','locations':[]})


if __name__=='__main__':unittest.main()
