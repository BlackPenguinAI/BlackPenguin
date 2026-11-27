import contextlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from startup_evidence import PREFIX, event, collect_events
from healthcheck import check


class StartupEvidenceTests(unittest.TestCase):
    def test_exception_message_never_exported(self):
        f=io.StringIO()
        with contextlib.redirect_stdout(f):
            try:raise RuntimeError('SECRET_PASSWORD postgres://private')
            except RuntimeError as exc:event('api_import','FAIL',exc=exc)
        self.assertNotIn('SECRET_PASSWORD',f.getvalue())
        self.assertEqual(collect_events(f.getvalue())[0]['exception_type'],'RuntimeError')
    def test_only_known_fields(self):
        raw='raw credentials\n'+PREFIX+json.dumps({'phase':'api_import','status':'FAIL','message':'private','locations':[{'file':'/private/db.py','line':1},{'file':'router.py','line':7}], 'extra':'secret'})
        self.assertEqual(collect_events(raw),[{'phase':'api_import','status':'FAIL','locations':[{'file':'router.py','line':7}]}])
    def test_malformed_ignored(self):
        self.assertEqual(collect_events(PREFIX+'not json\n'+PREFIX+'{"phase":[],"status":"FAIL"}'),[])
    def test_http_503_preserved_without_body(self):
        body=b'{"detail":{"reason":"schema_incompatible","secret":"private"}}'
        error=HTTPError('http://localhost',503,'private',{},io.BytesIO(body))
        with patch('healthcheck.urlopen',side_effect=error),contextlib.redirect_stdout(io.StringIO()) as f:
            self.assertEqual(check(),1)
        self.assertEqual(collect_events(f.getvalue()),[{'phase':'health_http','status':'FAIL','reason':'schema_incompatible','http_status':503}])
    def test_connection_failure(self):
        with patch('healthcheck.urlopen',side_effect=URLError('private')),contextlib.redirect_stdout(io.StringIO()) as f:
            self.assertEqual(check(),1)
        self.assertEqual(collect_events(f.getvalue())[0]['reason'],'connection_error')
    def test_readiness_not_weakened(self):
        class Response(io.BytesIO):status=200
        for body,code in [(b'{"status":"ready"}',0),(b'{"status":"not_ready"}',1),(b'not json',1)]:
            with self.subTest(body=body),patch('healthcheck.urlopen',return_value=Response(body)),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(check(),code)

if __name__=='__main__':unittest.main()
