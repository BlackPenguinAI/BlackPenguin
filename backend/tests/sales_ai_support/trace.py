"""Proposed evidence contract for subsequent groups; no live wiring in A."""
from dataclasses import dataclass, field
import json

VERSION = 'sales-ai-test-trace/1.0'
PHASES = {'inbound','context','understanding','plan','tool','compose','validate','persist','dispatch','complete'}
FORBIDDEN = {'api_key','access_token','refresh_token','auth_token','password','secret',
             'chain_of_thought','hidden_reasoning','reasoning_content','credentials','authorization'}


def assert_safe(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN or normalized.endswith(('_secret','_password','_ciphertext','_api_key','_access_token','_refresh_token','_auth_token')):
                raise ValueError('Secrets and hidden reasoning are not evidence.')
            assert_safe(item)
    elif isinstance(value, list):
        for item in value:
            assert_safe(item)


@dataclass
class TurnTrace:
    clock: object
    company_id: str
    project_id: str
    lead_id: str
    conversation_id: str
    inbound_message_id: str
    run_id: str
    code_commit: str
    configuration_id: str | None = None
    configuration_version: int | None = None
    model: str | None = None
    events: list = field(default_factory=list)

    def __post_init__(self):
        if not all(getattr(self,k) for k in ('company_id','project_id','lead_id','conversation_id','inbound_message_id','run_id','code_commit')):
            raise ValueError('A trace needs explicit scope and provenance.')

    def record(self, phase, *, status, evidence=None):
        if phase not in PHASES or status not in {'ok','failed','skipped','pending'}:
            raise ValueError('Unknown evidence event.')
        if self.events and self.events[-1]['phase']=='complete':
            raise ValueError('A completed trace is immutable.')
        evidence = evidence or {}
        assert_safe(evidence)
        # Force a JSON-safe deep copy; callers cannot mutate recorded evidence.
        evidence = json.loads(json.dumps(evidence,allow_nan=False))
        event = {'sequence':len(self.events)+1,'phase':phase,'status':status,
                 'at':self.clock.now().isoformat(),'evidence':evidence}
        self.events.append(event)
        return event

    def export(self):
        return {'version':VERSION,'source':'OFFLINE_TEST',
                **{k:getattr(self,k) for k in ('company_id','project_id','lead_id','conversation_id','inbound_message_id','run_id','code_commit','configuration_id','configuration_version','model')},
                'events':json.loads(json.dumps(self.events)), 'external_actions':0,
                'model_quality_evaluated':False}
