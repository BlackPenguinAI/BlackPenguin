"""Literal independent question coverage. Read intent is not a payment preference."""
import re


def financing_quotes(text):
    from app.modules.governance.services import request_attribution
    if request_attribution(text)['current_text']!=text:return []
    if re.search(r"\b(?:if|suppose|friend|said|says|told|he|she|they)\b",text,re.I):return []
    quotes=[]
    for clause in re.split(r'[.!?;\n]|\b(?:and|but|also)\b',text,flags=re.I):
        clause=clause.strip(' ,')
        pattern=(r'(?:(?:please |could you |can you |would you )?(?:explain|describe)|tell (?:me|us) about|'
                 r'what (?:are|is)|which (?:are|is)) (?:the |your |available )?'
                 r'(?:financing|payment|mortgage|loan)(?: options?| methods?| plans?| details?)?(?: please)?')
        if re.fullmatch(pattern,clause,re.I):quotes.append(clause)
        elif re.fullmatch(r'(?:What|Which) (?:financing|payment|mortgage|loan) (?:options?|plans?|methods?) (?:do you (?:offer|have)|are available)',clause,re.I):quotes.append(clause)
    return quotes


def normalize(value,text):
    quotes=financing_quotes(text)
    if not quotes or value.requires_clarification:return value,[]
    if any(getattr(value,k) for k in ('constraints','releases','comparison','cancellation','reschedule','wait','moderation','appointment_query')):return value,[]
    if any(r.topic.value=='financing' and r.polarity=='exclude' for r in value.requests):return value,[]
    data=value.model_dump(mode='json');notes=[]
    question=lambda evidence:evidence.strip(' .!?;') in quotes
    kept=[]
    for pref in data['preferences']:
        if pref['key']=='financing' and question(pref['evidence']):
            notes.append({'field':'preferences','action':'financing_question_not_payment_declaration','evidence':pref['evidence']})
        else:kept.append(pref)
    data['preferences']=kept
    if not value.permits('financing'):
        key='current_financing_question'
        while any(r['id']==key for r in data['requests']):key+='x'
        data['requests'].append(dict(id=key,topic='financing',polarity='request',evidence=quotes[0],reference_id=None))
        data['all_of'].append(key)
        notes.append({'field':'requests','action':'restore_independent_financing_question','evidence':quotes[0],'effect_authorization':False,'confidence_unchanged':value.confidence})
    if not notes:return value,[]
    from .understanding_contract import Understanding
    return Understanding.model_validate(data).check_evidence(text),notes


def issues(value,text):
    if financing_quotes(text) and not value.permits('financing') and not value.requires_clarification:
        return [{'location':['requests'],'type':'independent_financing_question_missing','message':'Preserve the current explicit financing-policy question as an independent financing request, outside material OR alternatives. It is not a payment preference.'}]
    # A separate question must be AND, not swallowed by a material OR.
    grouped={rid for g in value.alternatives for rid in g.request_ids}
    if financing_quotes(text) and any(r.topic.value=='financing' and r.polarity=='request' and (r.id not in value.all_of or r.id in grouped) for r in value.requests):
        return [{'location':['alternatives'],'type':'independent_financing_question_in_material_or','message':'The independent financing question is required alongside the material alternatives. Keep its request in all_of, outside the material OR.'}]
    return []
