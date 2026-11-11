"""Terminal courtesy is not opt-out, a meeting mutation or a new qualification gate."""
import re
from .financial_declarations import neutral_courtesy

GOODBYE="You're welcome. Thank you for your interest and have a good day. You can message again whenever another question comes up."
OTHER_QUESTION='Is there another property question I can help with?'


def terminal_text(text):
    from app.modules.governance.services import request_attribution
    return len(text)<=2000 and request_attribution(text)['current_text']==text and neutral_courtesy(text) and bool(re.search(
        r"\b(?:no (?:other|more|further) questions|nothing else|that['’]s all|goodbye|bye|have a (?:good|nice) day)\b",text,re.I))


def terminal_understanding(u,text):
    from .understanding_contract import Understanding
    if not terminal_text(text):return u
    data=u.model_dump(mode='json')
    data.update(requests=[],all_of=[],alternatives=[],constraints=[],references=[],preferences=[],
        preference_withdrawals=[],personal_facts=[],source_purposes=[],objections=[],empathy=None,
        comparison=None,releases=[],visit=None,reschedule=None,cancellation=None,wait=None,moderation=None,
        appointment_query=None,selected_reference_id=None,courtesy={'kind':'farewell','evidence':text},
        requires_clarification=False,clarification_question=None,confidence=1.0)
    return Understanding.model_validate(data)


def closing(u):
    substantive={r.topic.value for r in u.requests if r.polarity=='request'}-{'other','appointment','human'}
    if substantive:return None
    if u.courtesy and u.courtesy.kind=='farewell':return GOODBYE
    if (u.visit and u.visit.action=='decline') or (u.courtesy and u.courtesy.kind=='decline') or any(c.topic.value=='appointment' for c in u.constraints):
        return OTHER_QUESTION
    return None
