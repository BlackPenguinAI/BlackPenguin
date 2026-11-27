import unittest
from guard import validate, allowed_route, DB, HOST, PURPOSE, ADMIN

class GuardTests(unittest.TestCase):
    def env(self):
        e={'ENVIRONMENT':'staging','HEI06A2_PURPOSE':PURPOSE,'HEI06A2_INSTANCE':'1'*64,'SECRET_KEY':'2'*64,'HERMES_INTERNAL_TOKEN':'3'*64,'FIRST_SUPERADMIN_PASSWORD':'4'*64,'APP_COMMIT_SHA':'a'*40,'DATABASE_URL':f'postgresql+psycopg2://{DB}:'+('5'*64)+f'@{HOST}:5432/{DB}','FIRST_SUPERADMIN_EMAIL':ADMIN,'PUBLIC_APP_URL':'http://127.0.0.1:18082','OPENROUTER_API_KEY':'test-only','META_ACCESS_TOKEN':'test-only','TWILIO_LIVE_SMS_ENABLED':'false'}
        return e
    def test_valid(self):self.assertEqual(validate(self.env()),'1'*64)
    def test_production_environment(self):
        with self.assertRaises(PermissionError):validate({**self.env(),'ENVIRONMENT':'production'})
    def test_wrong_database(self):
        e=self.env();e['DATABASE_URL']=e['DATABASE_URL'].replace(HOST,'production-db')
        with self.assertRaises(PermissionError):validate(e)
    def test_wrong_db_query(self):
        e=self.env();e['DATABASE_URL']+='?sslmode=disable'
        with self.assertRaises(PermissionError):validate(e)
    def test_reused_secret(self):
        with self.assertRaises(PermissionError):validate({**self.env(),'SECRET_KEY':'1'*64})
    def test_external_key(self):
        for k in ('OPENROUTER_API_KEY','TELNYX_API_KEY','GOOGLE_CALENDAR_CLIENT_SECRET','FIREBASE_API_KEY','SMTP_PASSWORD'):
            with self.subTest(k=k),self.assertRaises(PermissionError):validate({**self.env(),k:'not-allowed'})
    def test_public_url(self):
        with self.assertRaises(PermissionError):validate({**self.env(),'PUBLIC_APP_URL':'https://blackpenguin.ai'})
    def test_login_and_policy(self):
        for method,path in [('POST','/api/v1/auth/login'),('GET','/api/v1/ai/hermes/global'),('POST','/api/v1/ai/hermes/drafts'),('POST','/api/v1/ai/hermes/versions/abc-123/publish'),('PUT','/api/v1/ai/hermes/engine')]:
            self.assertTrue(allowed_route(method,path))
    def test_external_routes(self):
        for method,path in [('POST','/api/v1/webhooks/telnyx/messaging'),('GET','/api/v1/sales/calendar/google/callback'),('POST','/api/v1/sales-agent/live-leads'),('POST','/api/v1/sales-agent/conversations/abc/manual-message'),('POST','/api/v1/auth/forgot-password'),('POST','/api/v1/auth/firebase/exchange'),('POST','/api/v1/sales-agent/simulate')]:
            self.assertFalse(allowed_route(method,path))
    def test_no_path_prefix_escape(self):
        for path in ['/api/v1/ai/hermes/versions/a/../../webhooks/meta','/api/v1/ai/hermes/versions/a/publish/extra','/api/v1/ai/hermes/global/']:
            self.assertFalse(allowed_route('POST',path))
    def test_no_arbitrary_writes(self):
        for method in ('POST','PUT','PATCH','DELETE','OPTIONS'):
            self.assertFalse(allowed_route(method,'/api/v1/projects'))

if __name__=='__main__':unittest.main()
