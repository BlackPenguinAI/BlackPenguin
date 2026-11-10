"""Versioned understanding contracts. These describe intent, never authorize writes."""
from enum import Enum
from typing import Literal, get_args
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
    detail_fields: list[Literal['bedrooms','bathrooms','area','kitchen','features','description']] = Field(default_factory=list,max_length=6)
    feature: str | None = Field(default=None,min_length=1,max_length=80)

    @model_validator(mode='after')
    def subject_scope(self):
        if self.subject is not None and self.topic != Topic.materials:
            raise ValueError('A material subject requires the materials topic.')
        if (self.detail_fields or self.feature) and self.topic != Topic.property_details:
            raise ValueError('Focused property fields require a property details request.')
        if self.feature and not set(self.detail_fields)&{'features','kitchen'}:
            raise ValueError('A feature name requires a focused feature or kitchen request.')
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


PreferenceKey = Literal['property', 'budget', 'bedrooms', 'bathrooms', 'location', 'delivery', 'purchase_timeline', 'financing', 'buyer_type', 'visit_readiness', 'motivation', 'decision_structure', 'needs']
BuyerSegment = Literal['first_time_buyer','move_up_buyer','relocation','downsizing','rental_yield_investor','appreciation_resale_investor','portfolio_diversification']
BUYER_SEGMENTS = frozenset(get_args(BuyerSegment))


class Preference(StrictModel):
    key: PreferenceKey
    value: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=2000)
    status: Literal['declared','declined'] = 'declared'


class PreferenceWithdrawal(StrictModel):
    key: PreferenceKey
    evidence: str = Field(min_length=1, max_length=2000)


class SourcePurposeClassification(StrictModel):
    field: Literal['buyer_type','motivation']
    record_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    segment: BuyerSegment


class ObjectionDeclaration(StrictModel):
    kind: Literal['price','timing','comparison','trust','approval']
    action: Literal['raise','resolve']
    evidence: str = Field(min_length=1,max_length=2000)


class Empathy(StrictModel):
    kind: Literal['feeling_unwell','personal_setback','frustrated']
    evidence: str = Field(min_length=1,max_length=2000)


class PersonalFact(StrictModel):
    key: Literal['age', 'occupation']
    action: Literal['set', 'withdraw', 'decline']
    evidence: str = Field(min_length=1, max_length=2000)


class Comparison(StrictModel):
    request_id: str = Field(min_length=1, max_length=60)
    reference_ids: list[str] = Field(default_factory=list, max_length=20)
    include_current: StrictBool = False
    include_all: StrictBool = False
    all_kind: Literal['property','unit'] = 'property'
    criteria: list[Literal['general', 'bedrooms', 'bathrooms', 'area', 'price', 'availability', 'kitchen', 'features']] = Field(min_length=1, max_length=8)
    feature: str | None = Field(default=None,min_length=1,max_length=80)
    operation: Literal['compare', 'maximum', 'minimum'] = 'compare'
    evidence: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def numeric_extreme(self):
        if self.operation != 'compare' and (len(self.criteria) != 1 or self.criteria[0] in {'general', 'kitchen', 'features'}):
            raise ValueError('An extremum needs one numeric criterion.')
        if len(set(self.reference_ids)) != len(self.reference_ids) or len(set(self.criteria)) != len(self.criteria):
            raise ValueError('Comparison members must be unique.')
        if self.feature is not None and not set(self.criteria)&{'general','features','kitchen'}:
            raise ValueError('A requested feature needs a feature comparison.')
        return self


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


class ModerationInterpretation(StrictModel):
    category: Literal['disagreement','off_topic','profanity','harassment','unauthorized_use','threat','security']
    evidence: str = Field(min_length=1,max_length=2000)


class WaitDirective(StrictModel):
    action: Literal['request','decline','cancel','nearby']
    evidence: str = Field(min_length=1,max_length=2000)
    timing: VisitTiming | None = None


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
    personal_facts: list[PersonalFact] = Field(default_factory=list, max_length=4)
    preference_withdrawals: list[PreferenceWithdrawal] = Field(default_factory=list, max_length=13)
    comparison: Comparison | None = None
    source_purposes: list[SourcePurposeClassification] = Field(default_factory=list,max_length=2)
    objections: list[ObjectionDeclaration] = Field(default_factory=list,max_length=5)
    empathy: Empathy | None = None
    releases: list[ConstraintRelease] = Field(default_factory=list, max_length=20)
    visit: VisitDirective | None = None
    courtesy: Courtesy | None = None
    reschedule: RescheduleDirective | None = None
    cancellation: CancellationDirective | None = None
    wait: WaitDirective | None = None
    moderation: ModerationInterpretation | None = None
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
        if len({p.key for p in self.personal_facts}) != len(self.personal_facts):
            raise ValueError('A personal field may change only once per turn.')
        if len({p.field for p in self.source_purposes}) != len(self.source_purposes):
            raise ValueError('A source purpose may be classified only once per turn.')
        if len({o.kind for o in self.objections}) != len(self.objections):
            raise ValueError('An objection may change only once per turn.')
        if {p.key for p in self.preferences} & {p.key for p in self.preference_withdrawals}:
            raise ValueError('A preference cannot be set and withdrawn together.')
        if len({p.key for p in self.preference_withdrawals}) != len(self.preference_withdrawals):
            raise ValueError('A preference may be withdrawn only once per turn.')
        if self.selected_reference_id and any(p.key=='property' for p in self.preference_withdrawals):
            raise ValueError('An interest cannot be selected and withdrawn together.')
        if self.comparison:
            c = self.comparison
            request = next((r for r in self.requests if r.id == c.request_id), None)
            if not request or request.polarity != 'request' or request.topic != Topic.catalog or request.reference_id:
                raise ValueError('A comparison must link an unbound affirmative catalog request.')
            if any(rid not in refs or next(r for r in self.references if r.id == rid).kind not in {'property','unit'} for rid in c.reference_ids):
                raise ValueError('Comparison references must identify properties or units.')
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
        from .evidence import anchor
        anchor(self.model_dump(mode='json'), inbound)
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
    pending_comparison: Comparison | None = None
    pending_comparison_references: list[Reference] = Field(default_factory=list,max_length=20)
    memory: 'TurnMemory' = Field(default_factory=lambda: TurnMemory())
    wait_context: dict = Field(default_factory=dict)
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


def response_schema(current_message=None):
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
    if current_message is not None:
        # A quote cannot be longer than its source. Preserve exact anchoring in
        # parse as the final authority; do not fuzzily rewrite consent/evidence.
        def bound(node):
            if isinstance(node, dict):
                evidence = node.get('properties', {}).get('evidence')
                if evidence is not None:
                    evidence['maxLength'] = min(2000, max(1, len(current_message)))
                    evidence['description'] = ('Copy a non-empty substring of current_message exactly. '
                        'Never append punctuation, quote history or normalize this field.')
                for child in node.values(): bound(child)
            elif isinstance(node, list):
                for child in node: bound(child)
        bound(schema)
    return schema


def decode(raw):
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
    return Understanding.model_validate(payload)


def parse(raw, inbound):
    from .evidence import anchor
    validated = decode(raw)
    anchored = anchor(validated.model_dump(mode='json'), inbound, repair_format=True)
    return Understanding.model_validate(anchored).check_evidence(inbound)
