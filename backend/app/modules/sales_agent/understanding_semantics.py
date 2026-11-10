"""Bounded semantic feedback. Never grants consent or rewrites model output."""
import re


def issues_for(value, text, *, appointment_offer=False):
    issues=[]
    def add(path,code,message):issues.append({'location':path,'type':code,'message':message})
    requests=value.requests
    # Only unambiguous first-person declarations, not questions or hypotheticals.
    cash=re.search(r'\b(?:I (?:can|will) pay (?:in )?cash|paying cash|I have cash available)\b',text,re.I)
    if cash and not re.search(r'\b(?:if|suppose|friend|said|not|don.t|cannot)\b|\?',text,re.I):
        if not any(p.key=='financing' and p.status=='declared' for p in value.preferences):
            add(['preferences'],'payment_declaration_missing','Capture the explicit own payment declaration as financing preference. It is not a financing-policy question.')
        for i,r in enumerate(requests):
            if r.topic.value=='financing' and re.fullmatch(r'\s*(?:paying cash|I (?:can|will) pay (?:in )?cash|I have cash available)[.!]?\s*',r.evidence,re.I):
                add(['requests',i],'declaration_as_question','A cash declaration is not a request about financing.')
    for i,r in enumerate(requests):
        if r.topic.value=='delivery' and re.search(r'\bnext (?:seven|7) days\b',r.evidence,re.I) and re.search(r'\b(?:visit|appointment|in.person)\b',text,re.I) and not re.search(r'\b(?:delivery|move.in|completion|construction)\b',r.evidence,re.I):
            add(['requests',i],'visit_timing_as_delivery','This is a visit date preference, not a property delivery question. Put the exact quote in visit.timing.')
    if appointment_offer and re.search(r'\b(?:I would like|I.d like|I choose|I.ll take) the (?:first|second|third) appointment\b',text,re.I):
        if value.permits('appointment') and not any(r.kind=='appointment' for r in value.references):
            add(['references'],'appointment_selection_reference_missing','The lead selects a previously offered appointment. Define a local appointment reference with exact selection evidence and link its request. Do not reinterpret it only as a new search.')
    if value.empathy and value.empathy.kind=='frustrated' and not re.search(r'\b(?:frustrat\w*|upset|annoy\w*|misunderstood|not understanding|don.t understand|aren.t understanding|not listening|angry)\b',text,re.I):
        # Do not reject arbitrary emotional language. This exact neutral refusal
        # was incorrectly classified in the observed production evaluation.
        if re.match(r'^(?:Understood|Thanks|Thank you)\b',text,re.I) and re.search(r'\b(?:do not|don.t|no)\b.{0,30}\b(?:book|alert|notification)\b',text,re.I):
            add(['empathy'],'neutral_refusal_as_frustration','A polite refusal of booking/alert is not evidence of frustration. Use acknowledgement and the explicit refusal.')
    return issues
