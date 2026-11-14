"""Bounded semantic feedback. Never grants consent or rewrites model output."""
import re

COMPARATIVE_SIGNAL=r"\b(?:compar\w*|differences?|similarities|cheaper|larger|smaller|bigger|better|best|worst|versus|vs|between|highest|lowest|most|least|more|less|other|alternatives?|which (?:one|property|option))\b"


def unrelated_financial_evidence(pref, *, appointment_confirmation=False):
    """Recognize appointment text substituted for a financial declaration.

    This is deliberately bounded: short contextual answers and unfamiliar money
    wording are not rejected. Mixed messages retain genuine financial clauses.
    """
    if pref.key not in {'budget', 'financing'}:
        return False
    quote=pref.evidence
    from .commercial_policy import down_payment_only
    if pref.key=='budget' and down_payment_only(quote):return True
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
            from .commercial_policy import down_payment_only
            add(['preferences',i],'down_payment_as_total_budget' if pref.key=='budget' and down_payment_only(pref.evidence) else 'financial_preference_unrelated_evidence',
                'Appointment selection/confirmation does not declare budget or financing. Omit this preference and retain the saved financial facts.')
    pure_action=re.search(r'\b(?:send|show)\b.*\b(?:PDF|brochure|photos?|images?|floor plan)\b|\b(?:arrange|book|schedule)\b.*\b(?:visit|viewing|appointment)\b|\bthe (?:first|second|third) appointment:',text,re.I)
    from .interpretation_consistency import POSITIVE_VISIT
    pure_action=pure_action or POSITIVE_VISIT.search(text)
    if value.visit and value.visit.action=='request' and POSITIVE_VISIT.search(text) and not value.requires_clarification and not any(r.topic.value=='appointment' and r.polarity=='request' for r in value.requests):
        add(['requests'],'visit_missing_executable_request','A visit request, selection or confirmation also needs a topic appointment request. Preserve its current evidence; do not infer final booking consent.')
    if value.comparison and pure_action and not re.search(COMPARATIVE_SIGNAL,text,re.I):
        add(['comparison'],'comparison_not_supported_by_action','This message requests material, a visit, or selects a time, not a comparison. Preserve the explicit action and omit the invented comparison. Never infer booking confirmation from a selection.')
    if value.visit and re.search(r'\b(?:send|show)\b.*\b(?:PDF|brochure|photos?|images?|floor plan)\b',value.visit.evidence,re.I) and not re.search(r'\b(?:visit|appointment|viewing|schedule|book)\b',value.visit.evidence,re.I):
        add(['visit'],'material_request_is_not_visit_consent','A request for material does not request, select or confirm a visit. Omit this unsupported directive.')
    requests=value.requests
    # Only unambiguous first-person declarations, not questions or hypotheticals.
    from .financial_declarations import cash_quotes,budget_quotes,pure_cash_quote,pure_budget_quote,neutral_courtesy,financing_question
    if cash_quotes(text):
        if not any(p.key=='financing' and p.status=='declared' for p in value.preferences):
            add(['preferences'],'payment_declaration_missing','Capture the explicit own payment declaration as financing preference. It is not a financing-policy question.')
        for i,r in enumerate(requests):
            if r.topic.value=='financing' and cash_quotes(r.evidence) and not financing_question(r.evidence):
                add(['requests',i],'declaration_as_question','A cash declaration is not a request about financing.')
    if budget_quotes(text) and not any(p.key=='budget' and p.status=='declared' for p in value.preferences):
        add(['preferences'],'budget_declaration_missing','Preserve the explicit own budget and currency as a budget preference, including during payment repair.')
    for i,r in enumerate(requests):
        if r.topic.value=='financing' and pure_cash_quote(r.evidence):
            add(['requests',i],'payment_declaration_as_question','This pure declaration means buying without financing, not requesting project financing information or executing payment.')
        if r.topic.value in {'inventory','catalog','pricing','delivery','financing'} and pure_budget_quote(r.evidence):
            add(['requests',i],'budget_declaration_as_question','A pure budget/payment declaration is not a project-information question. Capture preferences without inventing a request.')
        if r.topic.value in {'inventory','catalog'} and re.fullmatch(r'\s*Any (?:available )?time in the next (?:seven|7) days works(?: for me)?[;.!]?\s*',r.evidence,re.I):
            add(['requests',i],'visit_timing_as_inventory','This quote states visit timing, not inventory interest. Preserve visit timing and omit the invented inventory question.')
        if r.topic.value=='delivery' and re.search(r'\bnext (?:seven|7) days\b',r.evidence,re.I) and re.search(r'\b(?:visit|appointment|in.person)\b',text,re.I) and not re.search(r'\b(?:delivery|move.in|completion|construction)\b',r.evidence,re.I):
            add(['requests',i],'visit_timing_as_delivery','This is a visit date preference, not a property delivery question. Put the exact quote in visit.timing.')
    if appointment_offer and re.search(r'\b(?:I would like|I.d like|I choose|I.ll take) the (?:first|second|third) appointment\b',text,re.I):
        if value.permits('appointment') and not any(r.kind=='appointment' for r in value.references):
            add(['references'],'appointment_selection_reference_missing','The lead selects a previously offered appointment. Define a local appointment reference with exact selection evidence and link its request. Do not reinterpret it only as a new search.')
    if value.empathy and neutral_courtesy(value.empathy.evidence):
        add(['empathy'],'neutral_courtesy_as_emotion','A neutral acknowledgement or farewell does not establish an emotional state. Omit this optional affect.')
    if value.empathy and value.empathy.kind=='frustrated' and not re.search(r'\b(?:frustrat\w*|upset|annoy\w*|misunderstood|not understanding|don.t understand|aren.t understanding|not listening|angry)\b',text,re.I):
        # Do not reject arbitrary emotional language. This exact neutral refusal
        # was incorrectly classified in the observed production evaluation.
        if re.match(r'^(?:Understood|Thanks|Thank you)\b',text,re.I) and re.search(r'\b(?:do not|don.t|no)\b.{0,30}\b(?:book|alert|notification)\b',text,re.I):
            add(['empathy'],'neutral_refusal_as_frustration','A polite refusal of booking/alert is not evidence of frustration. Use acknowledgement and the explicit refusal.')
    return issues
