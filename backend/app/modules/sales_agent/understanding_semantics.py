"""Bounded semantic feedback. Never grants consent or rewrites model output."""
import re


def unrelated_financial_evidence(pref, *, appointment_confirmation=False):
    """Recognize appointment text substituted for a financial declaration.

    This is deliberately bounded: short contextual answers and unfamiliar money
    wording are not rejected. Mixed messages retain genuine financial clauses.
    """
    if pref.key not in {'budget', 'financing'}:
        return False
    quote=pref.evidence
    if appointment_confirmation and re.fullmatch(r"\s*(?:yes|yes please|confirmed|confirm|please do|go ahead|book it)[.!]?\s*",quote,re.I):
        return True
    appointment=re.search(r"\b(?:appointment|viewing|visit)\b",quote,re.I)
    selection=re.search(r"\b(?:I (?:would like|choose|prefer|confirm|will take)|I[’'](?:d like|ll take)|book|confirm|schedule|works for me)\b",quote,re.I)
    if not (appointment and selection):
        return False
    # The quote itself, rather than the model's value or historical profile,
    # must carry the financial meaning before it can replace a saved fact.
    signals=(r'\b(?:budget|USD|EUR|GBP|PEN|MXN|dollars?|soles|euros?|afford|spend|price|cost)\b|[$€£]'
             if pref.key=='budget' else
             r'\b(?:cash|financ\w*|mortgage|loan|credit|payment|pay|paying|paid|outright|contado)\b')
    return not re.search(signals,quote,re.I)


def issues_for(value, text, *, appointment_offer=False):
    issues=[]
    def add(path,code,message):issues.append({'location':path,'type':code,'message':message})
    for i,pref in enumerate(value.preferences):
        if unrelated_financial_evidence(pref):
            add(['preferences',i],'financial_preference_unrelated_evidence',
                'Appointment selection/confirmation does not declare budget or financing. Omit this preference and retain the saved financial facts.')
    requests=value.requests
    # Only unambiguous first-person declarations, not questions or hypotheticals.
    cash=re.search(r'\b(?:I (?:can|will) pay (?:in )?cash|paying cash|I have cash available)\b',text,re.I)
    if cash and not re.search(r'\b(?:if|suppose|friend|said|not|don.t|cannot)\b|\?',text,re.I):
        if not any(p.key=='financing' and p.status=='declared' for p in value.preferences):
            add(['preferences'],'payment_declaration_missing','Capture the explicit own payment declaration as financing preference. It is not a financing-policy question.')
        for i,r in enumerate(requests):
            if r.topic.value=='financing' and re.search(r'\b(?:paying cash|I (?:can|will) pay (?:in )?cash|I have cash available)\b',r.evidence,re.I) and not re.search(r'\?|\b(?:what|how|which|can I|do you|does|accept|options|allowed|offer)\b',r.evidence,re.I):
                add(['requests',i],'declaration_as_question','A cash declaration is not a request about financing.')
    budget=re.search(r'\bmy budget(?: is|:)\s*[\d,.]+\s*(?:USD|EUR|GBP|PEN|MXN)\b',text,re.I)
    if budget and not re.search(r'\b(?:if|suppose|friend|said|not)\b',text,re.I) and not any(p.key=='budget' and p.status=='declared' for p in value.preferences):
        add(['preferences'],'budget_declaration_missing','Preserve the explicit own budget and currency as a budget preference, including during payment repair.')
    for i,r in enumerate(requests):
        if r.topic.value=='financing' and re.fullmatch(r'\s*(?:paying cash|I (?:can|will) pay (?:in )?cash|I have cash(?: available)?)[.!]?\s*',r.evidence,re.I):
            add(['requests',i],'payment_declaration_as_question','This pure declaration means buying without financing, not requesting project financing information or executing payment.')
        if r.topic.value in {'inventory','catalog','pricing','delivery','financing'} and re.fullmatch(r'\s*My budget(?: is|:)\s*[\d,.]+\s*(?:USD|EUR|GBP|PEN|MXN)(?:,?\s+paying cash)?[.!]?\s*',r.evidence,re.I):
            add(['requests',i],'budget_declaration_as_question','A pure budget/payment declaration is not a project-information question. Capture preferences without inventing a request.')
        if r.topic.value in {'inventory','catalog'} and re.fullmatch(r'\s*Any (?:available )?time in the next (?:seven|7) days works(?: for me)?[;.!]?\s*',r.evidence,re.I):
            add(['requests',i],'visit_timing_as_inventory','This quote states visit timing, not inventory interest. Preserve visit timing and omit the invented inventory question.')
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
