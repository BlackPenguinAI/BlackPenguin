"""Persistent staging identity. Does not change any production readiness gate."""
import os
import re
from urllib.parse import urlsplit

DB = 'bp_hei06a2_staging'
HOST = 'staging-postgres'
PURPOSE = 'hei06a2-closed-persistent-v1'
ADMIN = 'staging-admin@example.invalid'
HEX = re.compile(r'[0-9a-f]{64}\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')


def require(condition, message):
    if not condition:
        raise PermissionError(message)


def validate(env=None):
    e = os.environ if env is None else env
    require(e.get('ENVIRONMENT') == 'staging' and e.get('HEI06A2_PURPOSE') == PURPOSE, 'Wrong staging purpose')
    for name in ('HEI06A2_INSTANCE','SECRET_KEY','HERMES_INTERNAL_TOKEN','FIRST_SUPERADMIN_PASSWORD'):
        require(bool(HEX.fullmatch(e.get(name,''))), 'Invalid staging secret/identity format')
    require(len({e[k] for k in ('HEI06A2_INSTANCE','SECRET_KEY','HERMES_INTERNAL_TOKEN','FIRST_SUPERADMIN_PASSWORD')}) == 4, 'Distinct staging secrets required')
    require(bool(SHA.fullmatch(e.get('APP_COMMIT_SHA',''))), 'Missing candidate SHA')
    url = urlsplit(e.get('DATABASE_URL',''))
    require(url.scheme == 'postgresql+psycopg2' and url.hostname == HOST and url.port == 5432 and url.path == '/'+DB and url.username == DB and bool(HEX.fullmatch(url.password or '')) and not url.query and not url.fragment, 'Wrong database identity')
    require(url.password not in {e[k] for k in ('HEI06A2_INSTANCE','SECRET_KEY','HERMES_INTERNAL_TOKEN','FIRST_SUPERADMIN_PASSWORD')}, 'Distinct DB secret required')
    require(e.get('FIRST_SUPERADMIN_EMAIL') == ADMIN and e.get('PUBLIC_APP_URL') == 'http://127.0.0.1:18082', 'Wrong local staging identity')
    require(e.get('OPENROUTER_API_KEY') == 'test-only' and e.get('META_ACCESS_TOKEN') == 'test-only', 'No external keys in this release')
    require(e.get('TWILIO_LIVE_SMS_ENABLED') == 'false', 'Live SMS prohibited')
    for k in ('TELNYX_API_KEY','TELNYX_AUTH_TOKEN','TWILIO_ACCOUNT_SID','TWILIO_AUTH_TOKEN','GOOGLE_CALENDAR_CLIENT_ID','GOOGLE_CALENDAR_CLIENT_SECRET','GOOGLE_APPLICATION_CREDENTIALS','FIREBASE_PROJECT_ID','FIREBASE_API_KEY','FIREBASE_AUTH_DOMAIN','FIREBASE_ADMIN_BRIDGE_URL','FIREBASE_ADMIN_BRIDGE_SECRET','SMTP_PASSWORD'):
        require(not e.get(k), 'External credential prohibited')
    return e['HEI06A2_INSTANCE']


def attest(conn, *, allow_fresh=False):
    from sqlalchemy import text
    instance = validate()
    db, user, version = conn.execute(text("SELECT current_database(), current_user, current_setting('server_version_num')")).one()
    require((db,user) == (DB,DB) and 160000 <= int(version) < 170000, 'Wrong PostgreSQL identity')
    rows = conn.execute(text('SELECT purpose, instance_id, candidate_commit FROM hei06a2_guard')).all()
    require(len(rows)==1 and tuple(rows[0][:2]) == (PURPOSE,instance), 'Wrong database marker')
    commit = rows[0][2]
    require(commit == os.environ['APP_COMMIT_SHA'] or (allow_fresh and commit is None), 'Candidate differs: backup and reviewed migration required')
    return commit


def allowed_route(method, path):
    # This is a closed control-plane environment, not a webhook or sales ingress.
    if method == 'GET':
        if path in {'/','/api/v1/health/version','/api/v1/health/ready','/api/v1/health/sales','/api/v1/users/me','/api/v1/ai/hermes/global','/api/v1/ai/hermes/engine','/api/v1/ai/hermes/versions','/api/v1/sales-agent/conversations'}:
            return True
        return any(re.fullmatch(pattern,path) for pattern in (
            r'/api/v1/ai/hermes/versions/[A-Za-z0-9-]{1,36}',
            r'/api/v1/ai/hermes/staff/conversations/[A-Za-z0-9-]{1,36}/context',
            r'/api/v1/sales-agent/conversations/[A-Za-z0-9-]{1,36}/(?:messages|operational-context)',
        ))
    if method == 'POST':
        return path in {'/api/v1/auth/login','/api/v1/ai/hermes/drafts'} or bool(re.fullmatch(r'/api/v1/ai/hermes/versions/[A-Za-z0-9-]{1,36}/(?:publish|restore)',path))
    # The real endpoint will reject Hermes selection through its existing gate.
    return method == 'PUT' and path == '/api/v1/ai/hermes/engine'
