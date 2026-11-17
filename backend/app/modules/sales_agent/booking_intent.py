"""One bounded wire-contract normalization for an explicit NEW visit request.

Never infers final booking consent. The model may hallucinate historical catalog
comparisons; only CURRENT first-person visit evidence can produce a read/request.
No database, model, external requests or permission checks are performed here.
"""
import re

# True comparative language. Generic 'more' and 'options' are deliberately NOT
# sufficient: they regularly refer to appointment slots instead of properties.
EXPLICIT_COMPARISON = re.compile(
    r"\b(?:compar(?:e|ing|ison)|differenc(?:e|es)|versus|vs\.?|cheaper|"
    r"larger|smaller|bigger|better than|worse than|best among|"
    r"more expensive|less expensive|which (?:property|home|house) is)\b", re.I,
)
NEW_VISIT = re.compile(
    r"\b(?:want|would like|need|plan|prefer)\s+to\s+"
    r"(?:(?:book|arrange|schedule|organize|have)\s+(?:an?\s+)?"
    r"(?:in[ -]person\s+)?(?:visit|viewing|appointment)|visit|view)\b",
    re.I,
)
# Conservative guards: mixed, conditional or reported requests remain for the
# usual model validation. Never turn somebody else's wish into lead consent.
UNSAFE_CONTEXT = re.compile(
    r"\b(?:if|suppose|hypothetical|my friend|a friend|he said|she said|"
    r"they said|do not|don't|never|cancel|reschedule)\b", re.I,
)


def canonicalize_new_visit(data, current_message, approved_property_names=()):
    """Derive ONE appointment request from a verified current visit directive.

    Only removes model-generated comparison requests if the CURRENT message
    contains no explicit comparison. All independent requests, customer
    preferences and restrictions are preserved unchanged.

    Safe failures return the input untouched to the existing strict validators.
    """
    directive = data.get('visit') or {}
    quote = directive.get('evidence')
    if (directive.get('action') != 'request' or not isinstance(quote, str)
        or not quote or quote not in current_message or
        not NEW_VISIT.search(quote) or UNSAFE_CONTEXT.search(current_message) or
        EXPLICIT_COMPARISON.search(current_message) or data.get('requires_clarification') or
        any(data.get(k) for k in ('constraints', 'releases', 'alternatives',
                                  'cancellation', 'reschedule', 'wait', 'moderation',
                                  'appointment_query'))):
        return data, []
    rows = data.get('requests') or []
    if any(r.get('polarity') != 'request' for r in rows):
        return data, []
    # A genuine material request or other independent request must survive.
    comparisons = [r for r in rows if r.get('topic') == 'comparison']
    appointment = [r for r in rows if r.get('topic') == 'appointment']
    if not comparisons and appointment:
        return data, []
    if not comparisons and not appointment:
        # Do not reinterpret otherwise valid non-comparison LLM messages here.
        return data, []
    fixed = {**data, 'requests': [r for r in rows if r.get('topic') != 'comparison']}
    changes = []
    if comparisons:
        changes.append({'field': 'requests', 'action': 'reject_unrequested_comparison',
                        'reason': 'no_current_comparative_evidence'})
    if not appointment:
        matches = []
        for name in approved_property_names:
            if isinstance(name, str) and name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', current_message, re.I):
                if name.casefold() not in {existing.casefold() for existing in matches}:
                    matches.append(name)
        # Bind only the unique property explicitly named by the lead; otherwise
        # let existing scoped-reference resolution/clarification decide.
        target = None
        if len(matches) == 1:
            literal = re.search(r'(?<!\w)' + re.escape(matches[0]) + r'(?!\w)', current_message, re.I).group()
            target = {'kind': 'property', 'expression': literal, 'evidence': literal}
        fixed['requests'].append({'topic': 'appointment', 'subject': None,
                                  'polarity': 'request', 'evidence': quote,
                                  'target': target})
        changes.append({'field': 'requests', 'action': 'derive_appointment_from_current_visit',
                        'source': 'quoted_visit_directive', 'effect_authorization': False})
    # Historical selection cannot become current-message quotation. If it was
    # invented by the model, avoid invoking the compiler with that false quote.
    selection = fixed.get('selection')
    if (selection and isinstance(selection, dict) and
            selection.get('evidence') not in current_message):
        fixed['selection'] = None
        changes.append({'field': 'selection', 'action': 'discard_unquoted_historical_selection'})
    return fixed, changes
