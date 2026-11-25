"""Explicit, revisable commercial preferences from Hermes v13.3.3 demo.

P01 fidelity module. USD-only data keys are preserved intentionally; P02
will map approved currency-aware BlackPenguin values without changing semantics.
"""
from __future__ import annotations
import copy
import re
from datetime import datetime, timezone

_AMOUNT = r"\$?\s*(\d{2,7}(?:,\d{3})*(?:\.\d+)?)\s*([km])?"
_BEDS = r"([1-9]|1\d)\s*[- ]?\s*(?:bedrooms?|beds?)\b"


def empty() -> dict:
    return {'revision':0,'budget':{'mode':'unknown','minimum_usd':None,'maximum_usd':None,
            'target_usd':None,'exact_price_usd':None,'currency':'USD'},
            'bedrooms':{'mode':'unknown','minimum':None,'maximum':None,'preferred':None},
            'last_source_message_id':None}


def amount(fragment: str) -> int | None:
    m=re.search(_AMOUNT,fragment,flags=re.I)
    if not m:return None
    value=float(m.group(1).replace(',',''))
    multiplier={'k':1000,'m':1_000_000}.get((m.group(2) or '').lower(),1)
    return int(value*multiplier) if value>0 else None


def _amounts(fragment: str) -> list[int]:
    return [amount(m.group(0)) for m in re.finditer(_AMOUNT,fragment,re.I)]


def parse_declarations(message: str) -> dict:
    """Conservatively parse explicit English buyer declarations, never questions."""
    text=str(message or '').strip().lower()
    if not text or '?' in text:return {}
    changes={}
    buyer=bool(re.search(r"\b(?:my|our|i|we|i'm|i've|i can|we can|i'd|i do|i dont|i don't)\b",text))
    if buyer:
        clause=re.search(r"\b(?:budget|spend|afford|pay|price|listing|price range|price bracket|cost|funds|available|go up to|max|maximum|min|minimum)\b",text)
        if clause:
            between=re.search(r"\b(?:between|from)\s*"+_AMOUNT+r"\s*(?:and|to|-)\s*"+_AMOUNT,text,flags=re.I)
            if between:
                low=amount(between.group(1)+(between.group(2) or ''))
                high=amount(between.group(3)+(between.group(4) or ''))
                if low and high and low<=high:
                    changes['budget']={'mode':'range','minimum_usd':low,'maximum_usd':high}
            else:
                numbers=_amounts(text)
                if numbers:
                    value=numbers[-1]
                    if re.search(r'\b(?:exact(?:ly)?\s+(?:priced?|price|listing)|(?:listing\s+)?price\s+(?:must|should)\s+be\s+exactly|(?:listing\s+)?price\s+exactly|(?:listing\s+)?(?:priced?)\s+at\s+exactly)\b',text):
                        changes['budget']={'mode':'exact_price','exact_price_usd':value}
                    elif re.search(r'\b(?:no more than|not more than|up to|at most|maximum|max\b|ceiling|under|less than|(?:do not|don.t|dont) want to spend more than|go up to|raise my budget to|increase my budget to|my new maximum is)\b',text):
                        changes['budget']={'mode':'cap','maximum_usd':value}
                    elif re.search(r'\b(?:at least|minimum|min\b|from\s+\$|above)\b',text):
                        changes['budget']={'mode':'floor','minimum_usd':value}
                    elif re.search(r'\b(?:exactly|fixed|only have|have exactly)\b',text):
                        changes['budget']={'mode':'fixed_funds','target_usd':value,'maximum_usd':value}
                    elif re.search(r'\b(?:about|around|approximately|roughly|near|close to)\b',text):
                        changes['budget']={'mode':'target','target_usd':value}
                    elif re.search(r'\b(?:my|our)\s+budget\b|\b(?:can|willing to)\s+(?:spend|afford|pay)\b',text):
                        changes['budget']={'mode':'target','target_usd':value}
    if re.search(r'\b(?:bedrooms?|beds?)\b',text):
        pairs=re.search(r"\b(?:between|from)\s*([1-9]|1\d)\s*(?:and|to|-)\s*([1-9]|1\d)\s*(?:bedrooms?|beds?)\b",text)
        if pairs:
            lo,hi=int(pairs.group(1)),int(pairs.group(2))
            if lo<=hi:changes['bedrooms']={'mode':'range','minimum':lo,'maximum':hi}
        else:
            matched=re.search(_BEDS,text) or re.search(r'\b(?:bedrooms?|beds?)\s*(?:of|:)?\s*([1-9]|1\d)\b',text)
            if matched and re.search(r'\b(?:i|we|my|our|want|need|looking|prefer|require|minimum|maximum|exactly|at least|at most)\b',text):
                n=int(matched.group(1))
                if re.search(r'\b(?:exactly|only|strictly|no more and no less)\b',text):
                    changes['bedrooms']={'mode':'exact','preferred':n}
                elif re.search(r'\b(?:at least|minimum|min\b|or more)\b',text):
                    changes['bedrooms']={'mode':'minimum','minimum':n}
                elif re.search(r'\b(?:at most|no more than|maximum|max\b|or fewer)\b',text):
                    changes['bedrooms']={'mode':'maximum','maximum':n}
                else:changes['bedrooms']={'mode':'preferred','preferred':n}
    return changes


def apply(state: dict, changes: dict, *, source_message_id: str | None = None) -> dict:
    """Atomic replacement with evidence and revision; preserve history."""
    current=state.setdefault('search_preferences',empty())
    next_value=copy.deepcopy(current)
    updated=[]
    for group in ('budget','bedrooms'):
        modification=changes.get(group)
        if not modification:continue
        previous=next_value[group]
        mode=modification.get('mode',previous['mode'])
        if group=='budget':
            if mode not in ('unknown','cap','floor','range','target','fixed_funds','exact_price'):
                return {'error':'Unsupported budget interpretation.'}
            b={**empty()['budget'],'mode':mode,'currency':'USD'}
            if mode=='cap':
                b['maximum_usd']=modification.get('maximum_usd',previous.get('maximum_usd'))
                b['minimum_usd']=previous.get('minimum_usd') if previous.get('mode')=='range' else None
                if b['minimum_usd'] is not None:b['mode']='range'
            elif mode=='floor':
                b['minimum_usd']=modification.get('minimum_usd',previous.get('minimum_usd'))
                b['maximum_usd']=previous.get('maximum_usd') if previous.get('mode')=='range' else None
                if b['maximum_usd'] is not None:b['mode']='range'
            elif mode=='range':
                b['minimum_usd']=modification.get('minimum_usd',previous.get('minimum_usd'))
                b['maximum_usd']=modification.get('maximum_usd',previous.get('maximum_usd'))
            elif mode=='target':
                b['target_usd']=modification.get('target_usd',previous.get('target_usd'))
            elif mode=='fixed_funds':
                b['target_usd']=modification.get('target_usd',previous.get('target_usd'))
                b['maximum_usd']=modification.get('maximum_usd',b['target_usd'])
            elif mode=='exact_price':
                b['exact_price_usd']=modification.get('exact_price_usd',previous.get('exact_price_usd'))
            numbers=[b[k] for k in ('minimum_usd','maximum_usd','target_usd','exact_price_usd') if b[k] is not None]
            if not numbers or any(not isinstance(n,int) or n<=0 or n>=100_000_000 for n in numbers):
                return {'error':'Budget requires positive, valid USD amounts.'}
            if b['minimum_usd'] is not None and b['maximum_usd'] is not None and b['minimum_usd']>b['maximum_usd']:
                return {'error':'Minimum budget cannot exceed maximum budget.'}
            next_value[group]=b
        else:
            if mode not in ('unknown','preferred','exact','minimum','maximum','range'):
                return {'error':'Unsupported bedroom interpretation.'}
            b={**empty()['bedrooms'],'mode':mode}
            if mode in ('preferred','exact'):b['preferred']=modification.get('preferred',previous.get('preferred'))
            elif mode=='minimum':b['minimum']=modification.get('minimum',previous.get('minimum'))
            elif mode=='maximum':b['maximum']=modification.get('maximum',previous.get('maximum'))
            elif mode=='range':
                b['minimum']=modification.get('minimum',previous.get('minimum'))
                b['maximum']=modification.get('maximum',previous.get('maximum'))
            nums=[b[k] for k in ('minimum','maximum','preferred') if b[k] is not None]
            if not nums or any(not isinstance(n,int) or not 1<=n<=20 for n in nums):
                return {'error':'Bedroom criteria require counts from 1 to 20.'}
            if b['minimum'] is not None and b['maximum'] is not None and b['minimum']>b['maximum']:
                return {'error':'Minimum bedrooms cannot exceed maximum bedrooms.'}
            next_value[group]=b
        if next_value[group]!=previous:updated.append(group)
    if not updated:return {'ok':True,'changed_fields':[],'search_preferences':current}
    prior=copy.deepcopy(current)
    next_value['revision']=current.get('revision',0)+1
    next_value['last_source_message_id']=source_message_id
    state.setdefault('search_preferences_history',[]).append({
        'prior':prior,'changes':copy.deepcopy(changes),
        'source_message_id':source_message_id,'changed_at':datetime.now(timezone.utc).isoformat()})
    state['search_preferences_history']=state['search_preferences_history'][-100:]
    state['search_preferences']=next_value
    if 'budget' in updated:
        state['lead']['budget_usd']=next_value['budget']['maximum_usd']
    if 'bedrooms' in updated:
        b=next_value['bedrooms'];state['lead']['min_bedrooms']=b['minimum'] if b['minimum'] is not None else b['preferred']
    return {'ok':True,'changed_fields':updated,'search_preferences':next_value}


def filter_unit(unit: dict, prefs: dict) -> tuple[bool,list[str],list[str]]:
    budget=prefs.get('budget') or empty()['budget']
    beds=prefs.get('bedrooms') or empty()['bedrooms']
    price=int(unit['price_usd']);count=int(unit['bedrooms'])
    violations=[]; preferences=[]
    if budget.get('minimum_usd') is not None and price<budget['minimum_usd']:
        violations.append('Below the minimum price range specified by the lead')
    if budget.get('maximum_usd') is not None and price>budget['maximum_usd']:
        violations.append('Exceeds the declared maximum budget')
    if budget.get('exact_price_usd') is not None and price!=budget['exact_price_usd']:
        violations.append('Not the exact listing price requested')
    if beds.get('minimum') is not None and count<beds['minimum']:
        violations.append('Fewer bedrooms than required')
    if beds.get('maximum') is not None and count>beds['maximum']:
        violations.append('More bedrooms than allowed')
    if beds.get('mode')=='exact' and count!=beds['preferred']:
        violations.append('Does not match the exact bedroom count')
    if beds.get('mode')=='preferred' and count!=beds['preferred']:
        preferences.append('Different bedroom count from the preferred number')
    return not violations,violations,preferences
