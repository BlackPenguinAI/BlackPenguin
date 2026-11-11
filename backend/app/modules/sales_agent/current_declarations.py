"""Independently validated current commercial statements; no action authority."""
import re
from .understanding_contract import Preference,Understanding,BUYER_SEGMENTS
from .financial_declarations import BUDGET,budget_quotes,cash_quotes,clauses,own_assertion,no_loan_removed
from .commercial_policy import down_payment_only

PURPOSES={
 'first_time_buyer':r'\bI (?:am buying|want to buy) my first (?:home|house|property)\b',
 'move_up_buyer':r'\bI (?:want|need) to (?:move|upgrade)[^.!?]{0,90}\b(?:larger|bigger) (?:home|house)\b',
 'relocation':r'\bI (?:am relocating|need to relocate|want to relocate)\b',
 'downsizing':r'\bI (?:want|need) to downsize\b',
 'rental_yield_investor':r'\bI (?:am buying|want to buy)[^.!?]{0,100}\brental income\b',
 'appreciation_resale_investor':r'\bI (?:am investing|want to invest)[^.!?]{0,100}\b(?:appreciation|resale)\b',
 'portfolio_diversification':r'\bI (?:want|need) to diversify[^.!?]{0,80}\b(?:portfolio|real estate)\b',
}
NEGATIVE=re.compile(r"\b(?:not|never|if|suppose|friend|colleague|he|she|they|said|says|told|withdraw|forget|don.t|cannot|can.t|maybe|might)\b",re.I)


def frame(preferences):
    return Understanding.model_validate(dict(version='sales-understanding/1.0',requests=[],all_of=[],alternatives=[],constraints=[],references=[],preferences=preferences,requires_clarification=False,clarification_question=None,confidence=1.0))


def extract(text,raw=None):
    """Only unambiguous current quotations, never history or model values alone.

    Literal money/cash patterns are shared with the existing semantics. Purpose
    classification is limited to explicit first-person declarations; multiple
    motivations stay unclassified instead of choosing a persona by demographics.
    """
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text'];prefs=[]
    def add(key,value,quote):
        if not quote or quote not in own or len(quote)>2000:return
        if key not in {p.key for p in prefs}:prefs.append(Preference(key=key,value=value,evidence=quote,status='declared'))
    budget=budget_quotes(own)
    ambiguous_budget=any(q in clause and re.search(r'\bor\b',clause,re.I) for q in budget for clause in clauses(own))
    if len(budget)==1 and not ambiguous_budget and not down_payment_only(own):
        match=re.fullmatch(BUDGET,budget[0],re.I)
        if match:add('budget',match[1].replace(',','')+' '+match[2].upper(),budget[0])
    cash=cash_quotes(own)
    if cash and not any(re.search(r'\bor\b',q,re.I) for q in cash) and not NEGATIVE.search(no_loan_removed(own)):
        add('financing','cash',cash[0])
    purposes=[]
    for clause in clauses(own):
        if NEGATIVE.search(clause) or not own_assertion(clause):continue
        for key,pattern in PURPOSES.items():
            if re.search(pattern,re.sub(r"\bI['’]m\b",'I am',clause),re.I):purposes.append((key,clause))
    if len({key for key,quote in purposes})==1:
        key,quote=purposes[0];add('buyer_type',key,quote)
    # Existing broader declarations remain model-interpreted, but have to pass
    # their own validators independently of every request in the packet.
    if raw:
        try:
            from .interpretation_input import document
            obj=document(raw)
            candidates=[]
            for item in obj.get('preferences',[]):
                try:p=Preference.model_validate(item)
                except (ValueError,TypeError):continue
                if p.status!='declared' or p.evidence not in own or not own_assertion(p.evidence):continue
                if p.key=='budget' and ambiguous_budget:continue
                if p.key=='financing' and any(p.evidence in clause and re.search(r'\bor\b',clause,re.I) for clause in clauses(own)):continue
                if p.key in {'budget','financing'}:
                    from .understanding_repair import verified_preferences
                    candidates.extend(verified_preferences(frame([p]),text))
                elif len({key for key,quote in purposes})<=1 and p.key in {'buyer_type','motivation'} and p.value in BUYER_SEGMENTS and not NEGATIVE.search(p.evidence) and {key for key,pattern in PURPOSES.items() if re.search(pattern,re.sub(r"\bI['’]m\b",'I am',p.evidence),re.I)}=={p.value} and any(p.evidence in clause and own_assertion(clause) and not NEGATIVE.search(clause) for clause in clauses(own)):
                    candidates.append(p)
            for p in candidates:
                if p.key not in {r.key for r in prefs}:prefs.append(p)
        except (ValueError,TypeError,AttributeError):pass
    return prefs


def merge(value,preferences):
    """Preserve current literal declarations only when not withdrawn/conflicting."""
    data=value.model_dump(mode='json');notes=[];withdrawn={p.key for p in value.preference_withdrawals}
    for p in preferences:
        if p.key in withdrawn:continue
        existing=next((x for x in data['preferences'] if x['key']==p.key),None)
        if existing and existing['status']=='declined':continue
        if existing and existing['value']==p.value:continue
        if existing:
            # Evidence is still the exact current statement. Replace an optional
            # stale/unsupported normalization, never a different declaration.
            if existing['evidence'] not in p.evidence and p.evidence not in existing['evidence']:continue
            data['preferences'].remove(existing)
        data['preferences'].append(p.model_dump(mode='json'))
        notes.append({'field':p.key,'action':'preserve_independently_validated_current_declaration','evidence':p.evidence})
    return Understanding.model_validate(data),notes


def declarations_only(quote):
    values=extract(quote)
    rest=quote
    for p in sorted(values,key=lambda p:len(p.evidence),reverse=True):rest=rest.replace(p.evidence,'')
    return bool(values) and not re.search(r'\w',rest)
