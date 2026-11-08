"""Versioned understanding contracts. These describe intent, never authorize writes."""
from enum import Enum
from typing import Literal
import json
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Topic(str, Enum):
    catalog = 'catalog'
    property_details = 'property_details'
    inventory = 'inventory'
    pricing = 'pricing'
    financing = 'financing'
    delivery = 'delivery'
    amenities = 'amenities'
    location = 'location'
    materials = 'materials'
    appointment = 'appointment'
    human = 'human'
    opt_out = 'opt_out'
    other = 'other'


Subject = Literal['brochure', 'photos', 'floor_plan', 'virtual_tour', 'price_list', 'location_map', 'unit_sheet']


class Request(StrictModel):
    id: str = Field(min_length=1, max_length=60, pattern=r'^[a-zA-Z0-9_-]+$')
    topic: Topic
    subject: Subject | None = None
    polarity: Literal['request', 'exclude']
    evidence: str = Field(min_length=1, max_length=2000)
    reference_id: str | None = Field(default=None,max_length=60)

    @model_validator(mode='after')
    def subject_scope(self):
        if self.subject is not None and self.topic != Topic.materials:
            raise ValueError('A material subject requires the materials topic.')
        return self


class Alternative(StrictModel):
    id: str = Field(min_length=1, max_length=60)
    request_ids: list[str] = Field(min_length=2, max_length=20)
    evidence: str = Field(min_length=1, max_length=2000)


class Constraint(StrictModel):
    topic: Topic
    subject: Subject | None = None
    effect: Literal['prohibit'] = 'prohibit'
    scope: Literal['turn', 'until_explicit_change']
    evidence: str = Field(min_length=1, max_length=2000)
    reference_id: str | None = Field(default=None,max_length=60)

    @model_validator(mode='after')
    def subject_scope(self):
        if self.subject is not None and self.topic != Topic.materials:
            raise ValueError('A material subject requires the materials topic.')
        return self


class Reference(StrictModel):
    kind: Literal['property', 'unit', 'appointment', 'location', 'material', 'ambiguous']
    id: str | None = Field(default=None,min_length=1,max_length=60)
    expression: str = Field(min_length=1, max_length=300)
    evidence: str = Field(min_length=1, max_length=2000)


class Preference(StrictModel):
    key: Literal['property', 'budget', 'bedrooms', 'location', 'delivery', 'purchase_timeline', 'financing', 'buyer_type', 'visit_readiness']
    value: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=2000)


class ConstraintRelease(StrictModel):
    topic: Topic
    subject: Subject | None = None
    evidence: str = Field(min_length=1, max_length=2000)


class VisitTiming(StrictModel):
    date_from_evidence: str | None = Field(default=None,max_length=200)
    date_until_evidence: str | None = Field(default=None,max_length=200)
    time_from_evidence: str | None = Field(default=None,max_length=100)
    time_until_evidence: str | None = Field(default=None,max_length=100)
    time_relation: Literal['any','exact','after','before','range','morning','afternoon','evening']='any'
    timezone_evidence: str | None = Field(default=None,max_length=100)
    duration_evidence: str | None = Field(default=None,max_length=100)


class VisitDirective(StrictModel):
    action: Literal['request','select','confirm','decline','reschedule','cancel']
    evidence: str = Field(min_length=1,max_length=2000)
    timing: VisitTiming | None = None


class Courtesy(StrictModel):
    kind: Literal['greeting','farewell','acknowledgement','decline']
    evidence: str = Field(min_length=1,max_length=2000)


class CancellationDirective(StrictModel):
    action: Literal['request','confirm','decline','reason']
    evidence: str = Field(min_length=1,max_length=2000)
    meeting_reference: str | None = Field(default=None,max_length=200)
    reason: str | None = Field(default=None,max_length=1000)


class RescheduleDirective(StrictModel):
    action: Literal['request','select','confirm','decline']
    evidence: str = Field(min_length=1,max_length=2000)
    meeting_reference: str | None = Field(default=None,max_length=200)
    target_project: str | None = Field(default=None,max_length=200)
    target_property: str | None = Field(default=None,max_length=200)
    target_unit: str | None = Field(default=None,max_length=200)
    target_location: str | None = Field(default=None,max_length=500)
    target_specialist: str | None = Field(default=None,max_length=200)
    timing: VisitTiming | None = None


class Understanding(StrictModel):
    version: Literal['sales-understanding/1.0']
    requests: list[Request] = Field(max_length=30)
    # Every member of all_of must be fulfilled; an alternative group needs
    # one suitable member, not an unconditional fan-out to all its members.
    all_of: list[str] = Field(max_length=30)
    alternatives: list[Alternative] = Field(max_length=15)
    constraints: list[Constraint] = Field(max_length=30)
    references: list[Reference] = Field(max_length=20)
    preferences: list[Preference] = Field(max_length=20)
    releases: list[ConstraintRelease] = Field(default_factory=list, max_length=20)
    visit: VisitDirective | None = None
    courtesy: Courtesy | None = None
    reschedule: RescheduleDirective | None = None
    cancellation: CancellationDirective | None = None
    appointment_query: Literal['active','past','cancelled','all'] | None = None
    selected_reference_id: str | None = Field(default=None,max_length=60)
    requires_clarification: StrictBool
    clarification_question: str | None = Field(max_length=500)
    confidence: float = Field(ge=0, le=1, strict=True)

    @model_validator(mode='after')
    def relations(self):
        refs=[r.id for r in self.references if r.id is not None]
        if len(refs)!=len(set(refs)):raise ValueError('Reference IDs must be unique.')
        linked=[r.reference_id for r in self.requests]+[c.reference_id for c in self.constraints]+[self.selected_reference_id]
        if any(value is not None and value not in refs for value in linked):raise ValueError('Unknown reference link.')
        if self.selected_reference_id and next(r for r in self.references if r.id==self.selected_reference_id).kind not in {'property','unit'}:
            raise ValueError('Only a property or unit reference can select commercial interest.')
        ids = [r.id for r in self.requests]
        if len(ids) != len(set(ids)):
            raise ValueError('Request identifiers must be unique.')
        affirmative_evidence = {(r.topic, r.subject, r.evidence) for r in self.requests if r.polarity == 'request'}
        if any((r.topic, r.subject, r.evidence) in affirmative_evidence for r in self.requests if r.polarity == 'exclude'):
            raise ValueError('The same evidence cannot request and exclude the same topic and subject.')
        affirmative = {r.id for r in self.requests if r.polarity == 'request'}
        members = list(self.all_of)
        group_ids = [g.id for g in self.alternatives]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError('Alternative identifiers must be unique.')
        for group in self.alternatives:
            if len(group.request_ids) != len(set(group.request_ids)):
                raise ValueError('An alternative cannot repeat a member.')
            members.extend(group.request_ids)
        if len(members) != len(set(members)) or set(members) != affirmative:
            raise ValueError('Every affirmative request must appear exactly once in all_of or an alternative; exclusions cannot be requirements.')
        if self.requires_clarification and not (self.clarification_question or '').strip():
            raise ValueError('Clarification must ask a concrete question.')
        if not self.requires_clarification and self.clarification_question is not None:
            raise ValueError('A clarification question requires the clarification flag.')
        return self

    def check_evidence(self, inbound: str):
        evidence = [r.evidence for r in self.requests] + [c.evidence for c in self.constraints]
        evidence += [g.evidence for g in self.alternatives] + [r.evidence for r in self.references]
        evidence += [p.evidence for p in self.preferences]
        evidence += [r.evidence for r in self.releases]
        if self.visit:
            evidence.append(self.visit.evidence)
            if self.visit.timing:
                evidence.extend(v for k,v in self.visit.timing.model_dump().items() if k!='time_relation' and v is not None)
        if self.reschedule:
            evidence.append(self.reschedule.evidence)
            evidence.extend(v for k,v in self.reschedule.model_dump().items() if k not in {'action','evidence','timing'} and v)
            if self.reschedule.timing:evidence.extend(v for k,v in self.reschedule.timing.model_dump().items() if k!='time_relation' and v is not None)
        if self.cancellation:
            evidence.extend(v for k,v in self.cancellation.model_dump().items() if k!='action' and v)
        if self.courtesy:evidence.append(self.courtesy.evidence)
        if any(not item.strip() or item not in inbound for item in evidence):
            raise ValueError('Evidence must be an exact non-empty substring of the current message.')
        return self

    def permits(self, topic: Topic | str, subject: str | None = None) -> bool:
        """Semantic gate only; permission, consent and tool checks still apply."""
        topic = Topic(topic)
        if self.requires_clarification:
            return False
        blocked = any(c.topic == topic and (c.subject is None or subject is None or c.subject == subject) for c in self.constraints)
        blocked |= any(r.topic == topic and r.polarity == 'exclude' and (r.subject is None or subject is None or r.subject == subject) for r in self.requests)
        return not blocked and any(r.topic == topic and r.polarity == 'request' and (r.subject is None or subject is None or r.subject == subject) for r in self.requests)


class Task(StrictModel):
    id: str = Field(min_length=1, max_length=60)
    topic: Topic
    status: Literal['pending', 'suspended', 'blocked', 'awaiting_user', 'completed', 'cancelled']
    request_ids: list[str] = Field(default_factory=list, max_length=30)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    subject: Subject | None = None
    source_message_id: str | None = Field(default=None, max_length=36)
    alternative_group: str | None = Field(default=None, max_length=100)
    property_id: str | None = Field(default=None, max_length=36)
    unit_id: str | None = Field(default=None,max_length=36)
    binding_status: Literal['unspecified','resolved','unresolved']='unspecified'
    blocked_reason: str | None = Field(default=None,max_length=300)
    last_read_signature: str | None = Field(default=None,max_length=64)


class Offer(StrictModel):
    kind: Literal['property', 'unit', 'appointment', 'location', 'material']
    message_id: str = Field(min_length=1, max_length=36)
    option_ids: list[str] = Field(max_length=200)
    expires_at: AwareDatetime | None = None
    status: Literal['current','suspended']='current'


class PropertyConstraint(StrictModel):
    topic: Topic
    subject: Subject | None = None
    scope: Literal['turn','until_explicit_change']
    evidence: str = Field(min_length=1,max_length=2000)
    property_id: str | None = Field(default=None,max_length=36)
    unit_id: str | None = Field(default=None,max_length=36)
    binding_status: Literal['resolved','unresolved']='resolved'


class ToolResult(StrictModel):
    version: Literal['sales-tool-result/1.0'] = 'sales-tool-result/1.0'
    operation_id: str = Field(min_length=1, max_length=100)
    status: Literal['success', 'empty', 'partial', 'revoked', 'denied', 'conflict', 'error', 'uncertain']
    evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    data: dict = Field(default_factory=dict)
    safe_message: str | None = Field(default=None, max_length=1000)


class TurnMemory(StrictModel):
    version: Literal['sales-turn-memory/1.0']='sales-turn-memory/1.0'
    as_of_message_id: str | None = Field(default=None,max_length=36)
    recent_turns: list[dict] = Field(default_factory=list,max_length=8)
    answered_topics: list[Topic] = Field(default_factory=list,max_length=30)


class ChangeProposal(StrictModel):
    id: str = Field(min_length=1,max_length=60)
    kind: Literal['reschedule','cancel','property_visit_change']
    meeting_id: str = Field(min_length=1,max_length=36)
    booking_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    expires_at: AwareDatetime
    target_project_id: str | None = Field(default=None,max_length=36)
    target_property_type_id: str | None = Field(default=None,max_length=36)
    target_unit_id: str | None = Field(default=None,max_length=36)
    starts_at: AwareDatetime | None = None
    availability: Literal['not_checked']='not_checked'


class DialogueState(StrictModel):
    version: Literal['sales-dialogue/1.0'] = 'sales-dialogue/1.0'
    selected_property_type_id: str | None = Field(default=None, min_length=1, max_length=36)
    selected_unit_id: str | None = Field(default=None,min_length=1,max_length=36)
    tasks: list[Task] = Field(default_factory=list, max_length=100)
    constraints: list[Constraint] = Field(default_factory=list, max_length=100)
    property_constraints: list[PropertyConstraint] = Field(default_factory=list,max_length=100)
    offers: list[Offer] = Field(default_factory=list, max_length=50)
    preferences: list[Preference] = Field(default_factory=list, max_length=100)
    last_understanding: Understanding | None = None
    memory: 'TurnMemory' = Field(default_factory=lambda: TurnMemory())
    cancellation_search: dict = Field(default_factory=dict)
    cancellation_proposal: dict | None = None
    cancellation_followup_id: str | None = None
    reschedule_search: dict = Field(default_factory=dict)
    reschedule_proposal: dict | None = None
    booking_search: dict = Field(default_factory=dict)
    booking_proposal: dict | None = None
    cadence_status: Literal['active','stopped'] = 'active'
    cadence_stop_reason: Literal['booked','farewell','declined','cancelled'] | None = None
    change_proposals: list['ChangeProposal'] = Field(default_factory=list,max_length=10)

    @model_validator(mode='after')
    def task_dependencies(self):
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError('Task identifiers must be unique.')
        dependencies = {t.id: set(t.depends_on) for t in self.tasks}
        done = set()
        def visit(key, path):
            if key in path:
                raise ValueError('Task dependencies cannot contain cycles.')
            if key in done:
                return
            for dependency in dependencies[key]:
                if dependency not in dependencies:
                    raise ValueError('Unknown task dependency.')
                visit(dependency, path | {key})
            done.add(key)
        for key in ids:
            visit(key, set())
        return self


def response_schema():
    """Provider-neutral strict JSON schema; importing this needs no settings/DB."""
    schema = Understanding.model_json_schema()
    def strict(node):
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object' and 'properties' in node:
                node['required'] = list(node['properties'])
                node['additionalProperties'] = False
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)
    strict(schema)
    return schema


def parse(raw, inbound):
    if not isinstance(raw, str) or len(raw.encode()) > 64000:
        raise ValueError('Invalid or oversized understanding response.')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON keys are not allowed.')
            result[key] = value
        return result
    try:
        payload = json.loads(raw, object_pairs_hook=pairs)
    except RecursionError as exc:
        raise ValueError('Understanding JSON is nested too deeply.') from exc
    return Understanding.model_validate(payload).check_evidence(inbound)
