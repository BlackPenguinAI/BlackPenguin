"""Fixed synthetic opportunity and read-only permission contract; no production gate."""
import re
from datetime import datetime, timezone

SCOPE = dict(company_id='stg-company', project_id='stg-project',
             conversation_id='stg-hermes-simulation', lead_id='stg-hermes-lead')
TOOLS = frozenset({'get_project_overview', 'get_unit_details', 'search_properties', 'compare_properties'})
MODEL = 'openai/gpt-4o-mini'
KEY = 'HEI06A2_SCOPED_OPENROUTER_API_KEY'
MAX_TURNS = 12
EVENT = re.compile(r'hermes:staged:[A-Za-z0-9_-]{1,80}\Z')


class ScopedDenied(PermissionError):
    """Only locally authored constant reason codes are exported."""


def require(ok, reason):
    if not ok:
        raise ScopedDenied(reason)


def check_input(event_id, content):
    require(isinstance(event_id, str) and bool(EVENT.fullmatch(event_id)), 'invalid_event')
    require(isinstance(content, str) and bool(content.strip()) and len(content.encode('utf-8')) <= 4000, 'invalid_synthetic_message')


def check_policy(snapshot):
    cfg = snapshot['configuration']
    require(bool(snapshot.get('published_version_id')) and cfg.get('enabled') is True, 'policy_not_enabled')
    tools = cfg.get('enabled_tools')
    require(isinstance(tools, list) and bool(tools) and set(tools) <= TOOLS, 'policy_tools_not_read_only')
    require(cfg.get('model') == MODEL and cfg.get('provider') == 'openrouter', 'model_not_certified')
    require(snapshot['engine_selection']['hermes_live_ready'] is False, 'production_gate_changed')
    return snapshot['published_version_id']


def check_grant(grant, policy_id, now=None):
    now = now or datetime.now(timezone.utc)
    require(grant and grant['active'] is True, 'grant_closed')
    require(grant['expires_at'] > now, 'grant_expired')
    require(grant['policy_id'] == policy_id, 'policy_changed')


def check_scope(project, lead, conversation):
    require(project.id == SCOPE['project_id'] and project.company_id == SCOPE['company_id'] and project.is_demo is True and project.is_active is True, 'project_outside_scope')
    require(lead.id == SCOPE['lead_id'] and lead.company_id == SCOPE['company_id'] and lead.project_id == SCOPE['project_id'] and lead.is_demo is True and lead.is_test is True and not lead.is_opt_out and not lead.deleted_at and lead.consent_status == 'granted_simulation' and lead.agent_status != 'human_control', 'lead_outside_scope')
    require(conversation.id == SCOPE['conversation_id'] and conversation.company_id == SCOPE['company_id'] and conversation.project_id == SCOPE['project_id'] and conversation.lead_id == SCOPE['lead_id'] and conversation.channel == 'simulation' and conversation.provider == 'simulation' and not conversation.is_paused, 'conversation_outside_scope')
