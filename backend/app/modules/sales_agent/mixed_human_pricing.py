"""A narrow read-only capability for a mixed human-contact and price question.

This never changes model confidence, interprets a new request, or grants any
booking/handoff side effect. The model's existing pricing request must already
be grounded in an exact user question and a unique approved property name.
"""
import re

# Only two independent literal clauses, both authored by the current lead.
# Unclear, quoted, reported, conditional, negated and mixed-action messages
# do not match the whole-string grammar and remain subject to clarification.
_CONTACT = (r"(?:I|we)\s+(?:still\s+)?(?:want|need|would\s+like)\s+to\s+"
            r"(?:speak|talk)\s+(?:with|to)\s+(?:(?:a|an)\s+)?"
            r"(?:human|person|sales representative|sales agent)")
_QUESTION = (r"(?P<question>(?:What\s+is\s+the\s+price\s+of\s+"
             r"(?P<property>[^.!?;\n]+)|How\s+much\s+does\s+"
             r"(?P<property_cost>[^.!?;\n]+)\s+cost)\?)")
_EXACT = re.compile(r"\s*"+_CONTACT+r"\s*[.!]\s*"+_QUESTION+r"\s*",re.I)


def normalize_misread_price_comparison(data, current_message, approved_names=()):
    """Repair a model-only comparison for one literal human+property price query.

    This runs after the spurious-visit removal and BEFORE internal references
    are compiled. It never adds a new user request, increases confidence,
    authorizes an effect, or chooses a property from historical context.
    """
    if not isinstance(data, dict) or not isinstance(current_message, str):
        return data, []
    match = _EXACT.fullmatch(current_message)
    if match is None or data.get('requires_clarification'):
        return data, []
    property_name = (match.group('property') or match.group('property_cost')).strip()
    question = match.group('question')
    if not property_name or not isinstance(approved_names, (list, tuple)):
        return data, []
    approved = [name for name in approved_names if isinstance(name, str)
                and name.casefold() == property_name.casefold()]
    if len(approved) != 1:
        return data, []
    if any(data.get(key) for key in (
        'visit', 'selection', 'alternatives', 'constraints', 'releases',
        'reschedule', 'cancellation', 'wait', 'moderation',
        'appointment_query', 'personal_facts', 'preference_withdrawals',
        'source_purposes', 'objections')):
        return data, []
    rows = data.get('requests') or []
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return data, []
    row = rows[0]
    members = row.get('members') or []
    if (row.get('topic') != 'comparison' or row.get('polarity') != 'request'
        or row.get('evidence') != question or row.get('operation') != 'compare'
        or row.get('all_kind') != 'property' or row.get('include_all')
        or row.get('include_current') or row.get('feature')
        or row.get('criteria') != ['price'] or len(members) != 1
        or not isinstance(members[0], dict)):
        return data, []
    member = members[0]
    if (member.get('kind') != 'property'
        or not isinstance(member.get('expression'), str)
        or member['expression'].strip().casefold() != property_name.casefold()
        or not isinstance(member.get('evidence'), str)
        or member['evidence'] not in question):
        return data, []
    # The name and question are literal current-message substrings, not inferred
    # catalog IDs. Backend resolution and policy/hold checks remain mandatory.
    fixed = {**data, 'requests': [{
        'topic': 'pricing', 'polarity': 'request', 'subject': None,
        'evidence': question,
        'target': {'kind': 'property', 'expression': property_name,
                   'evidence': property_name},
    }]}
    return fixed, [{
        'field': 'requests', 'action': 'single_price_question_not_comparison',
        'confidence_unchanged': data.get('confidence'),
        'effect_authorization': False,
    }]


def verified_mixed_price_read(value, text, commercial, *, human_step, holds=()):
    """True permits only a normal scoped pricing READ, never an effect.

    The existing planner must still resolve the reference and respect stored
    restrictions; the observation loop will fetch only approved catalog data.
    """
    if human_step != 'ask' or 'pricing' in (holds or ()) or not isinstance(text,str):
        return False
    match = _EXACT.fullmatch(text)
    if not match or value is None or value.requires_clarification:
        return False
    if any(getattr(value,k,None) for k in (
        'visit','comparison','constraints','alternatives','releases','reschedule',
        'cancellation','wait','moderation','appointment_query','personal_facts',
        'preference_withdrawals','source_purposes','objections')):
        return False
    if len(value.requests)!=1 or len(value.references)!=1:
        return False
    request,ref=value.requests[0],value.references[0]
    if (request.topic.value!='pricing' or request.polarity!='request' or
            request.evidence!=match.group('question') or request.reference_id!=ref.id or
            ref.kind!='property' or ref.evidence not in match.group('question')):
        return False
    property_name=(match.group('property') or match.group('property_cost')).strip()
    if ref.expression.strip().casefold()!=property_name.casefold():
        return False
    catalog=(commercial or {}).get('property_types') or []
    matches=[item for item in catalog if isinstance(item,dict) and
             isinstance(item.get('property_type'),str) and item['property_type'].casefold()==property_name.casefold() and
             item.get('id')]
    return len(matches)==1
