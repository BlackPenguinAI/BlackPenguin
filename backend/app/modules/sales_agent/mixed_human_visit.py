"""Bounded correction: a human-contact request is not an in-person visit.

This only REMOVES a model-created visit directive with no current evidence.
It never manufactures a commercial task, a booking permission or confidence.
Actual visit/booking language, hypotheticals and unclear messages fail closed.
"""
import re

OWN_CONTACT = re.compile(
    r"\b(?:I|we)\s+(?:still\s+)?(?:want|need|would like|wish)\s+to\s+"
    r"(?:speak|talk)\s+(?:with|to)\s+(?:(?:a|an)\s+)?"
    r"(?:human|person|sales representative|sales agent)\b", re.I,
)
VISIT_LANGUAGE = re.compile(
    r"\b(?:visit|viewing|tour|appointment|booking|book|schedule|reschedule|"
    r"in[ -]person|meeting|showing|walkthrough|walk-through|inspect|see|"
    r"meet\s+(?:in|at)|come\s+(?:in|over))\b", re.I,
)
UNSAFE_CONTEXT = re.compile(
    r"\b(?:if|suppose|hypothetical|my friend|a friend|he said|she said|"
    r"they said|reported|never|don't|do not)\b", re.I,
)


def omit_spurious_visit(data, current_message):
    """Return (wire input, audit notes) without granting or changing any action."""
    if not isinstance(data, dict) or not isinstance(current_message, str):
        return data, []
    visit = data.get('visit')
    if not isinstance(visit, dict) or visit.get('action') != 'request':
        return data, []
    quote = visit.get('evidence')
    if (not isinstance(quote, str) or not quote or quote not in current_message or
        not OWN_CONTACT.search(current_message) or
        VISIT_LANGUAGE.search(current_message) or UNSAFE_CONTEXT.search(current_message)):
        return data, []
    # This is a negative repair only: preserve all independent pricing and
    # other requests; their ordinary evidence, scope and permission checks apply.
    fixed = {**data, 'visit': None}
    return fixed, [{
        'field': 'visit',
        'action': 'omit_human_contact_misread_as_visit',
        'confidence_unchanged': data.get('confidence'),
        'effect_authorization': False,
    }]
