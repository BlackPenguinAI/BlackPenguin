"""Bounded own declarations; negating a loan is not negating an outright purchase."""
import re

BUDGET=r'My (?:(?:total purchase|total|overall|purchase) )?budget(?: is|:)\s*([\d,]+(?:\.\d+)?)\s*(USD|EUR|GBP|PEN|MXN)'
CASH=r'(?:I (?:can|will) pay (?:in )?cash|paying cash|I have cash(?: available)?|I (?:will|can) buy outright)'
NO_LOAN=r"(?:I\s+)?(?:do not|don't|don’t)\s+(?:need|require)\s+(?:any\s+)?financing"


def no_loan_removed(text):
    return re.sub(NO_LOAN,'',text,flags=re.I)


def own_assertion(text):
    return not re.search(r"\b(?:if|suppose|friend|he|she|they|said|says|told|forget|withdraw|not|don.t|cannot)\b|\?",no_loan_removed(text),re.I)


def ambiguous_or_withdrawn(text):
    return bool(re.search(r'\b(?:if|suppose|friend|he|she|they|said|says|told|forget|withdraw|cannot)\b',text,re.I))


def clauses(text):
    return [m.group().strip() for m in re.finditer(r'(?:[^.!?;\n]|\.(?=\d))+[.!?;]?',text)]


def cash_quotes(text):
    if ambiguous_or_withdrawn(text):return []
    result=[]
    for clause in clauses(text):
        if own_assertion(clause) and re.search(r'\b'+CASH+r'\b',clause,re.I):result.append(clause)
    return result


def pure_cash_quote(text):
    return bool(re.fullmatch(r'\s*'+CASH+r'(?:\s+and\s+'+NO_LOAN+r')?[.!]?\s*',text,re.I))


def pure_budget_quote(text):
    return bool(re.fullmatch(r'\s*'+BUDGET+r'(?:,?\s+paying cash)?[.!]?\s*',text,re.I))


def budget_quotes(text):
    if ambiguous_or_withdrawn(text):return []
    return [m.group(0) for m in re.finditer(r'\b'+BUDGET+r'\b',text,re.I)
        if any(m.group(0) in clause and own_assertion(clause) for clause in clauses(text))]


def neutral_courtesy(text):
    phrase=r"(?:no (?:other|more|further) questions(?: for now)?|nothing else(?: for now)?|that['’]s all|thanks(?: for (?:your |the )?help)?|thank you(?: for (?:your |the )?help)?|goodbye|bye|have a (?:good|nice) day)"
    return bool(re.fullmatch(r'\s*'+phrase+r'(?:[,.!;\s]+(?:and\s+)?'+phrase+r')*[,.!;\s]*',text,re.I))


def financing_question(text):
    return any(re.search(r'\b(?:what|how|which|can I|could I|do you|does|is there|are there|tell me|explain|show me)\b',clause,re.I)
        and re.search(r'\b(?:financ\w*|mortgage|loan|cash|payment\w*)\b',clause,re.I)
        and not pure_cash_quote(clause) and not pure_budget_quote(clause) for clause in clauses(text))
