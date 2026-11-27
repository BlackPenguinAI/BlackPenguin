"""HEI-06A.2b.2: narrow synthetic inbound acceptance capability.
No production module imports this file. No arbitrary IDs, messages or model keys.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from scoped_policy import check_policy, require, ScopedDenied

SCOPE = dict(company_id='stg-live-company', project_id='stg-live-project',
             conversation_id='stg-live-conversation', lead_id='stg-live-lead')
COMPANY_NAME = 'Synthetic Live Acceptance Company'
PROJECT_NAME = 'Synthetic Live Acceptance Homes'
LEAD_NAME = 'Synthetic Live Acceptance Buyer'
PHONE = '+15550000003'
KEY = 'HEI06A2_LIVE_OPENROUTER_API_KEY'
MARKER = 'hei06a2b2-synthetic-inbound-only-v1'
MESSAGES = {
    'first': 'Tell me the number of bedrooms in Van Buren.',
    'second': 'Tell me the number of bathrooms in Van Buren.',
    'revoked': 'What is the name of this project?',
}
TOOLS = frozenset({'get_project_overview', 'get_unit_details'})


def job_id(case):
    require(case in MESSAGES, 'unknown_fixture_case')
    return 'stg-live-job-' + case


def inbound_id(case):
    require(case in MESSAGES, 'unknown_fixture_case')
    return 'stg-live-in-' + case


def provider_id(case):
    require(case in MESSAGES, 'unknown_fixture_case')
    return 'hei06a2b2-synthetic-' + case


def event_id(case):
    return 'telnyx:' + provider_id(case)


@dataclass(frozen=True)
class Capability:
    case: str
    generation: str
    policy_id: str

    @property
    def job_id(self): return job_id(self.case)

    @property
    def inbound_id(self): return inbound_id(self.case)


def validate_case(case):
    require(case in MESSAGES, 'unknown_fixture_case')
    return case


def policy_id(snapshot):
    pid = check_policy(snapshot)
    require(set(snapshot['configuration']['enabled_tools']) == TOOLS, 'live_policy_not_exact_read_only')
    require(snapshot['engine_selection']['active_sales_engine'] == 'langgraph', 'global_selector_changed')
    return pid


def check_capability(row, cap, published, now=None):
    now = now or datetime.now(timezone.utc)
    require(isinstance(cap, Capability), 'missing_job_capability')
    validate_case(cap.case)
    require(row is not None and row['active'] is True, 'live_grant_closed')
    require(row['expires_at'] > now, 'live_grant_expired')
    require(all(row[k] == v for k, v in SCOPE.items()), 'live_grant_scope_mismatch')
    require(row['generation'] == cap.generation, 'live_generation_changed')
    require(row['policy_id'] == cap.policy_id == published, 'live_policy_changed')
    require(row['active_job'] == cap.job_id, 'live_job_not_leased')
    return cap


def check_entities(company, project, lead, conversation):
    require(company.id == SCOPE['company_id'] and company.name == COMPANY_NAME and company.is_active is True,
            'live_company_outside_scope')
    require(project.id == SCOPE['project_id'] and project.company_id == company.id and project.name == PROJECT_NAME
            and project.is_active is True and project.is_demo is False, 'live_project_outside_scope')
    # Live adapters reject demo rows; these are explicitly synthetic test rows
    # in a separately attested database, NOT an authorization for actual leads.
    require(lead.id == SCOPE['lead_id'] and lead.company_id == company.id and lead.project_id == project.id
            and lead.full_name == LEAD_NAME and lead.phone == PHONE and lead.is_test is True and lead.is_demo is False
            and not lead.deleted_at and not lead.is_opt_out and lead.consent_status == 'granted'
            and lead.agent_status == 'active', 'live_lead_outside_scope')
    require(conversation.id == SCOPE['conversation_id'] and conversation.company_id == company.id
            and conversation.project_id == project.id and conversation.lead_id == lead.id
            and conversation.provider == 'telnyx' and conversation.channel == 'sms'
            and conversation.provider_thread_key is None and not conversation.is_paused,
            'live_conversation_outside_scope')


def check_inbound(job, inbound, cap, statuses=('processing',)):
    require(job is not None and job.id == cap.job_id and job.conversation_id == SCOPE['conversation_id']
            and job.message_id == cap.inbound_id and job.status in statuses, 'live_job_scope_or_status')
    require(inbound is not None and inbound.id == cap.inbound_id and inbound.conversation_id == SCOPE['conversation_id']
            and inbound.provider_message_id == provider_id(cap.case) and inbound.content == MESSAGES[cap.case]
            and inbound.channel == 'sms' and inbound.direction == 'inbound' and inbound.role == 'user', 'live_inbound_mismatch')
    meta = inbound.metadata_json or {}
    require(meta.get('hei06a2b2_synthetic') == MARKER and meta.get('hei06a2b2_generation') == cap.generation
            and meta.get('lead_id') == SCOPE['lead_id'] and meta.get('project_id') == SCOPE['project_id']
            and meta.get('continuity_recorded') is True, 'live_inbound_not_authorized')


def check_delivery(cap, company_id, provider, recipient, body):
    require(isinstance(cap, Capability) and cap.case in ('first', 'second'), 'live_delivery_not_authorized')
    require(company_id == SCOPE['company_id'] and provider == 'telnyx' and recipient == PHONE
            and isinstance(body, str) and bool(body.strip()), 'live_delivery_outside_scope')
