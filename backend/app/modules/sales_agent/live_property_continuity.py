"""P3-A: select only a verified, delivered property-catalog ordinal.

A catalog ordinal is a choice of property, never an appointment time, a
material acceptance, or authorization for a booking. Historical/suspended
catalogs are intentionally not accepted here.
"""
import re

VERSION = 'sales-live-property-choice/1.0'
COMPETING = ('appointment_offer', 'booking_confirmation', 'material_offer',
             'location_offer', 'release_offer', 'control_confirmation',
             'qualification_offer', 'reschedule_confirmation',
             'cancellation_confirmation', 'wait_offer')


def decision(text, metadata, offered_ids, names, displayed_text):
    """Return (select|clarify, property_id) or None; no effect authorization.

    `offered_ids` come from the latest delivered backend offer, `names` from
    project-scoped, approved property rows, and `displayed_text` is the exact
    accepted message that the lead saw. All three must agree in ordering.
    """
    from .turn_context import choice_index
    if not text or len(text) > 120 or any(metadata.get(k) for k in COMPETING):
        return None
    idx = choice_index(text)
    if idx is None:
        # Same short reply with a harmless list qualifier; never reinterpret
        # a multi-intent message such as "second option and book a visit".
        match = re.fullmatch(
            r"\s*(?:(?:the|la|el)\s+)?(?:(?:option|opci[oó]n)\s+)?"
            r"(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)"
            r"(?:\s+(?:option|opci[oó]n))?"
            r"(?:\s+(?:of|from)\s+(?:the|that)\s+(?:list|options))?[.!]?\s*",
            text, re.I)
        words = {'first':0, 'second':1, 'third':2, 'fourth':3,
                 'fifth':4, '1st':0, '2nd':1, '3rd':2, '4th':3, '5th':4}
        idx = words.get(match.group(1).casefold()) if match else None
    if idx is None:
        return None
    ids = (metadata.get('property_catalog_offer') or {}).get('property_type_ids') or []
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
        return None
    if ids != offered_ids or len(set(ids)) != len(ids) or not all(
            isinstance(identifier, str) and identifier in names for identifier in ids):
        return ('clarify', None)
    if not 0 <= idx < len(ids):
        return ('clarify', None)
    # The metadata order alone is not proof of the order visible to the lead.
    # A separate paragraph of marketing copy cannot silently renumber a catalog.
    numbered = {}
    for row in re.finditer(r'(?m)^\s*(\d{1,2})[.)]\s+([^\r\n]+)', displayed_text or ''):
        number = int(row.group(1))
        if number in numbered:
            return ('clarify', None)
        numbered[number] = row.group(2).strip()
    if set(numbered) != set(range(1, len(ids) + 1)):
        return ('clarify', None)
    for number, identifier in enumerate(ids, 1):
        label = names[identifier]
        # A visible entry can contain bedrooms/prices after the exact label.
        if not re.match(r'^' + re.escape(label) + r'(?=$|[\s,;:–—-])',
                        numbered[number], re.I):
            return ('clarify', None)
    return ('select', ids[idx])


def try_preview(db, scope, conversation, inbound, *, state, previous_meta,
                expected_revision, event_key):
    """Deterministic *understanding preview*; planner still resolves the offer.

    There are no CRM changes, material sends or reservation actions here.
    """
    from .first_booking import accepted_outbound
    previous = accepted_outbound(db, conversation, 'property_catalog_offer')
    if not previous or previous_meta.get('property_catalog_offer') != (
            previous.metadata_json or {}).get('property_catalog_offer'):
        return None
    ids = ((previous.metadata_json or {}).get('property_catalog_offer') or {}).get('property_type_ids') or []
    offer = next((o for o in state.offers if o.kind == 'property' and
                  o.status == 'current' and o.message_id == previous.id and
                  o.option_ids == ids), None)
    if not offer:
        return None
    from app.modules.projects.models import ProjectPropertyType
    rows = db.query(ProjectPropertyType).filter(
        ProjectPropertyType.project_id == scope.project_id,
        ProjectPropertyType.id.in_(ids)).all()
    names = {row.id: row.name for row in rows}
    resolved = decision(inbound.content, previous_meta, offer.option_ids, names, previous.content)
    if not resolved:
        return None
    kind, identifier = resolved
    from .understanding_contract import Understanding
    from .dialogue_store import save
    from .understanding_service import PreviewOutcome
    if kind == 'select':
        content = dict(version='sales-understanding/1.0',
            requests=[dict(id='p3a_details', topic='property_details',
                           polarity='request', evidence=inbound.content,
                           reference_id='p3a_choice')],
            all_of=['p3a_details'], alternatives=[], constraints=[],
            references=[dict(id='p3a_choice', kind='property',
                             expression='option ' + str(ids.index(identifier) + 1), evidence=inbound.content)],
            preferences=[], selected_reference_id='p3a_choice',
            requires_clarification=False, clarification_question=None,
            confidence=1.0)
    else:
        content = dict(version='sales-understanding/1.0',
            requests=[], all_of=[], alternatives=[], constraints=[],
            references=[], preferences=[],
            requires_clarification=True,
            clarification_question='Which property name would you like to review?',
            confidence=1.0)
    understood = Understanding.model_validate(content).check_evidence(inbound.content)
    prepared = state.model_copy(deep=True, update={'last_understanding': understood})
    revision, saved = save(db, scope, event_key=event_key,
        expected_revision=expected_revision, state=prepared,
        kind='understanding_preview', metadata={
            'model':'deterministic-property-choice', 'inference_mode':'deterministic',
            'prompt_snapshot':{'version':VERSION,'model_invoked':False,'system':None},
            'prompt_configuration_id':None,'inbound_message_id':inbound.id,
            'expected_revision':expected_revision,'outcome':'accepted',
            'error_code':None,'input_contract':VERSION,
            'interpretation_attempts':[], 'validated_declarations':[],
            'decision':kind, 'selected_property_id':identifier,
            'effect_authorization':False})
    return PreviewOutcome(revision, saved, 'accepted', ())
