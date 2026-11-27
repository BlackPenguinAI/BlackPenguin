"""HEI-06A disposable acceptance harness; never import from a deployed API.

A fresh Compose-only PostgreSQL identity AND a database marker are required.
The test-local readiness override is not a staging/productive authorization.
"""
from __future__ import annotations
import os
import re
from urllib.parse import urlsplit

DB_NAME = 'bp_hei06a_test'
DB_HOST = 'hei06a-postgres'
PURPOSE = 'hei06a-disposable-synthetic-only-v1'
SCOPE = ('co', 'project', 'conversation', 'lead')
MESSAGE = 'Tell me the number of bedrooms in Van Buren.'
POLICY_TOOLS = ['get_project_overview', 'get_unit_details']


def validate_environment(env=None, *, sdk=False):
    env = os.environ if env is None else env
    if env.get('ENVIRONMENT') != 'test' or env.get('HEI06A_PURPOSE') != PURPOSE:
        raise PermissionError('Not the disposable HEI-06A harness')
    if not re.fullmatch(r'[a-f0-9]{40}', env.get('HEI06A_COMMIT', '')):
        raise PermissionError('Missing full candidate SHA')
    if not re.fullmatch(r'[a-f0-9]{64}', env.get('HERMES_INTERNAL_TOKEN', '')):
        raise PermissionError('Invalid private test token')
    if env.get('HEI06A_MODE') not in {'offline', 'model'}:
        raise PermissionError('Invalid evaluation mode')
    url = urlsplit(env.get('DATABASE_URL', ''))
    if (url.scheme != 'postgresql+psycopg2' or url.hostname != DB_HOST
            or url.port != 5432 or url.path != '/' + DB_NAME
            or url.username != DB_NAME or not re.fullmatch(r'[a-f0-9]{48}', url.password or '')
            or url.query or url.fragment):
        raise PermissionError('Invalid disposable database identity')
    key = env.get('OPENROUTER_API_KEY', '')
    if sdk and env['HEI06A_MODE'] == 'model':
        if not key or key == 'test-only':
            raise PermissionError('Explicit dedicated model key required')
    elif key != 'test-only':
        raise PermissionError('No model credentials in offline/worker processes')
    for name in ('TELNYX_API_KEY', 'TELNYX_AUTH_TOKEN', 'TWILIO_ACCOUNT_SID',
                 'TWILIO_AUTH_TOKEN', 'GOOGLE_CALENDAR_CLIENT_ID',
                 'GOOGLE_CALENDAR_CLIENT_SECRET', 'GOOGLE_APPLICATION_CREDENTIALS',
                 'FIREBASE_ADMIN_BRIDGE_SECRET', 'SMTP_PASSWORD'):
        if env.get(name):
            raise PermissionError('External provider credentials prohibited')
    if env.get('META_ACCESS_TOKEN') != 'test-only':
        raise PermissionError('Invalid test-only Meta setting')
    return env['HEI06A_MODE']


def check_database(connection):
    from sqlalchemy import text
    name, user, version = connection.execute(text(
        "SELECT current_database(), current_user, current_setting('server_version_num')"
    )).one()
    if (name, user) != (DB_NAME, DB_NAME) or not 160000 <= int(version) < 170000:
        raise PermissionError('Wrong server/database/user')
    markers = connection.execute(text('SELECT purpose FROM hei06a_test_guard')).scalars().all()
    if markers != [PURPOSE]:
        raise PermissionError('Missing disposable database marker')


def assert_scope(db, job_id, run_id=None):
    """Only the exact synthetic job, opportunity and published policy may run."""
    from app.modules.sales_agent.models import SalesInboundJob, SalesConversation, SalesMessage, AgentRun
    from app.modules.sales_crm.models import Lead
    from app.modules.hermes_sales_core.staff_models import HermesGlobalSettings, HermesGlobalVersion
    from app.modules.hermes_sales_core.staff_config import baseline
    from app.modules.companies.models import Company
    from app.modules.projects.models import Project
    job = db.get(SalesInboundJob, job_id)
    conversation = db.get(SalesConversation, job.conversation_id) if job else None
    lead = db.get(Lead, conversation.lead_id) if conversation else None
    inbound = db.get(SalesMessage, job.message_id) if job else None
    company = db.get(Company, SCOPE[0])
    project = db.get(Project, SCOPE[1])
    expected_policy = {**baseline(), 'enabled': True, 'enabled_tools': POLICY_TOOLS}
    version = db.get(HermesGlobalVersion, 'version')
    settings = db.get(HermesGlobalSettings, 'global')
    if (job_id != 'job' or not job or job.status != 'processing' or not conversation
            or (conversation.company_id, conversation.project_id, conversation.id, conversation.lead_id) != SCOPE
            or conversation.channel != 'sms' or conversation.provider != 'telnyx'
            or not company or company.name != 'Test Company' or not project or project.name != 'Test Homes'
            or project.company_id != SCOPE[0] or not lead or lead.phone != '+15550000001' or lead.full_name != 'Test Buyer'
            or not inbound or inbound.id != 'inbound' or inbound.content != MESSAGE
            or inbound.provider_message_id != 'provider-in' or inbound.direction != 'inbound'
            or not version or not version.is_published or not settings
            or settings.published_version_id != 'version'
            or version.configuration != expected_policy
            or settings.configuration != {**version.configuration, 'active_sales_engine': 'hermes'}):
        raise PermissionError('Outside exact synthetic scope')
    if run_id is not None:
        run = db.get(AgentRun, run_id)
        if (not run or run.conversation_id != conversation.id or run.event_id != 'telnyx:provider-in'
                or run.prompt_configuration_id != 'version' or run.status != 'running'
                or (run.input_snapshot or {}).get('message_id') != inbound.id):
            raise PermissionError('Not the exact reserved synthetic run')
    return job


def inference_count(db):
    from sqlalchemy import text
    return db.execute(text('SELECT count(*) FROM hei06a_test_inference')).scalar_one()
