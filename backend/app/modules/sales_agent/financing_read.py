"""Bounded read-only exception for an unambiguous current financing-policy question.

This does not raise model confidence or grant booking, message sending, human
contact, or policy bypass. Business tool authorization remains downstream.
"""
import re

_QUESTION = re.compile(
    r'(?:what|which) financing (?:options|plans) (?:do you offer|are available)\?'
    r'|do you offer financing\?'
    r'|how does (?:your )?financing work\?', re.I)
_DECLINE = re.compile(
    r'(?:I|we) (?:do not|don\'t) want (?:an? )?(?:in-person )?visit (?:yet|now)\.', re.I)


def verified_financing_policy_read(value, text, *, holds=()):
    """Permit normal scoped observation despite low confidence, never an effect.

    Fail closed for third-party speech, multi-intent, actions, unresolved
    references, prohibitions, and unsupported clauses. No model field is added.
    """
    if not value or not isinstance(text, str) or 'financing' in (holds or ()):
        return False
    if value.requires_clarification or value.confidence >= .8:
        return False
    body=text.strip()
    decline=_DECLINE.match(body)
    question=body[decline.end():].strip() if decline else body
    if not _QUESTION.fullmatch(question):
        return False
    if len(value.requests)!=1 or value.references or value.comparison or value.alternatives:
        return False
    if any(getattr(value,field,None) for field in (
            'reschedule','cancellation','wait','moderation','appointment_query',
            'selected_reference_id','releases','source_purposes','personal_facts',
            'preference_withdrawals','objections')):
        return False
    if value.visit and (not decline or value.visit.action!='decline'):
        return False
    if decline and (not value.visit or value.visit.action!='decline'):
        return False
    if any(c.topic.value!='appointment' or not decline for c in value.constraints):
        return False
    row=value.requests[0]
    return bool(row.topic.value=='financing' and row.polarity=='request'
        and row.evidence==question and row.reference_id is None
        and row.subject is None and value.permits('financing'))
