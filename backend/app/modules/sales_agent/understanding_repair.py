"""Exact-source quotation choices for the existing single provider repair."""
import copy
import json
import re


def evidence_choices(text, raw=None):
    choices=[]
    def add(value):
        if isinstance(value,str) and value.strip() and value in text and len(value)<=2000 and value not in choices:
            choices.append(value)
    add(text)
    try:
        data=json.loads(raw) if isinstance(raw,str) else {}
        from .evidence import quotations
        for item,key,path in quotations(data):add(item.get(key))
    except (ValueError,TypeError,AttributeError,KeyError):pass
    for match in re.finditer(r'[^.!?;\n]+[.!?;]?',text):add(match.group().strip())
    for match in re.finditer(r'[^,;.!?\n]+[,;.!?]?',text):add(match.group().strip())
    return choices[:16]


def constrained_repair_schema(schema, text, raw=None):
    result=copy.deepcopy(schema);choices=evidence_choices(text,raw)
    def constrain(node):
        if isinstance(node,dict):
            for key,field in node.get('properties',{}).items():
                if key=='evidence' or key.endswith('_evidence'):
                    branches=field.get('anyOf',[field])
                    for branch in branches:
                        if branch.get('type')!='string':continue
                        maximum=branch.get('maxLength',2000)
                        allowed=[quote for quote in choices if len(quote)<=maximum]
                        if allowed:branch['enum']=allowed
            for child in node.values():constrain(child)
        elif isinstance(node,list):
            for child in node:constrain(child)
    constrain(result)
    return result


def verified_preferences(value, text):
    """Independently verify narrow own declarations, not a rejected whole frame.

    No requests, references, consent, withdrawals or appointment directives are
    carried forward. Ambiguous/negated/reported declarations are left to the model.
    """
    from decimal import Decimal,InvalidOperation
    if re.search(r'\b(?:if|suppose|friend|said|says|told|forget|withdraw|not|don.t|cannot)\b',text,re.I):return []
    budgets=list(re.finditer(r'\bmy budget(?: is|:)\s*([\d,]+(?:\.\d+)?)\s*(USD|EUR|GBP|PEN|MXN)\b',text,re.I))
    result=[]
    for pref in value.preferences:
        if pref.status!='declared' or pref.evidence not in text:continue
        if pref.key=='budget' and len(budgets)==1:
            matched=re.fullmatch(r'\s*([\d,]+(?:\.\d+)?)\s*(USD|EUR|GBP|PEN|MXN)\s*',pref.value,re.I)
            if not matched or budgets[0].group(0) not in pref.evidence:continue
            try:equal=Decimal(matched[1].replace(',',''))==Decimal(budgets[0][1].replace(',',''))
            except InvalidOperation:equal=False
            if equal and matched[2].upper()==budgets[0][2].upper():result.append(pref)
        elif pref.key=='financing' and pref.value.casefold()=='cash':
            if re.search(r'\bI (?:can|will) pay (?:in )?cash\b',pref.evidence,re.I) or (budgets and re.search(r'\bpaying cash\b',pref.evidence,re.I)):
                result.append(pref)
    return result


def preserve_preferences(value, preserved):
    """Restore omissions only; never overwrite a later model interpretation."""
    existing={p.key for p in value.preferences}|{p.key for p in value.preference_withdrawals}
    missing=[p for p in preserved if p.key not in existing]
    if not missing:return value,[]
    data=value.model_dump(mode='json');data['preferences'] += [p.model_dump(mode='json') for p in missing]
    from .understanding_contract import Understanding
    return Understanding.model_validate(data),[{'field':p.key,'action':'restore_verified_current_declaration','source_attempt':1} for p in missing]


def omit_declaration_questions(value, issues):
    """Omit only pure budget/timing declarations mislabeled as questions.

    No linked alternative/comparison or exclusion is changed. A genuine question
    cannot match the full-declaration diagnostics used here.
    """
    from .understanding_contract import Understanding
    types={'budget_declaration_as_question','visit_timing_as_inventory','payment_declaration_as_question'}
    indexes={issue['location'][1] for issue in issues if issue['type'] in types and len(issue.get('location',[]))==2 and issue['location'][0]=='requests'}
    candidates=[r for i,r in enumerate(value.requests) if i in indexes and r.polarity=='request']
    ids={r.id for r in candidates}
    linked={rid for group in value.alternatives for rid in group.request_ids}
    if value.comparison:linked.add(value.comparison.request_id)
    ids-=linked
    if not ids:return value,[]
    data=value.model_dump(mode='json')
    data['requests']=[r for r in data['requests'] if r['id'] not in ids]
    data['all_of']=[rid for rid in data['all_of'] if rid not in ids]
    try:result=Understanding.model_validate(data)
    except ValueError:return value,[]
    return result,[{'field':'requests','request_id':r.id,'topic':r.topic.value,'action':'omit_question_invented_from_declaration'} for r in candidates if r.id in ids]


def omit_unrelated_financial_preferences(value, *, appointment_confirmation=False):
    """Remove only appointment-backed financial claims, with an audit receipt."""
    from .understanding_semantics import unrelated_financial_evidence
    bad=[p for p in value.preferences if unrelated_financial_evidence(p,appointment_confirmation=appointment_confirmation)]
    if not bad:return value,[]
    return value.model_copy(update={'preferences':[p for p in value.preferences if p not in bad]}),[
        {'field':p.key,'action':'omit_unrelated_financial_preference',
         'reason':'financial_preference_unrelated_evidence'} for p in bad]
