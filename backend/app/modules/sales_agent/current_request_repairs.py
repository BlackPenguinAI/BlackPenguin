"""Conservative repairs of literal format alternatives; no new business consent."""
import re
from .understanding_contract import Understanding

FORMATS={'photos':r'(?:photos?|pictures?|images?)','brochure':r'(?:brochure(?: PDF)?|PDF)','floor_plan':r'(?:floor plans?|blueprints?)'}

def normalize(value,text,commercial):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    # Keep exclusions, third-party speech, hypothetical and unknown named targets.
    if own!=text or re.search(r"\b(?:not|never|no|don['’]t|if|suppose|friend|said|says|told|he|she|they)\b",own,re.I):return value,[]
    if value.constraints or value.releases or value.comparison or value.cancellation or value.reschedule:return value,[]
    data=value.model_dump(mode='json');refs={r['id']:r for r in data['references']};notes=[]
    names={str(r.get('property_type') or '').casefold() for r in commercial.get('property_types',[])}
    files={str(r.get('name') or '').strip().casefold() for r in commercial.get('available_assets',[])}
    def format_of(phrase):
        return next((k for k,p in FORMATS.items() if re.fullmatch(r'(?:the |a |some )?'+p,phrase.strip(),re.I)),None)
    for row in data['requests']:
        if row['polarity']!='request' or row['evidence'] not in own:continue
        ref=refs.get(row['reference_id']);expression=ref['expression'] if ref else ''
        if row['topic']=='materials' and ref and expression.casefold() not in names|files:
            subject=format_of(expression)
            if subject and row['subject'] in {None,subject}:
                row.update(subject=subject,reference_id=None)
                notes.append({'field':'requests','action':'generic_format_is_subject_not_owner','evidence':expression})
        if row['topic']=='financing' and ref and expression.casefold() not in names and re.fullmatch(r'(?:the )?(?:financing|payment|mortgage|loan)(?: options?| methods?| information| details)?',expression,re.I):
            row['reference_id']=None
            notes.append({'field':'references','action':'generic_financing_is_not_property','evidence':expression})
    # Restore a literal OR only between two existing positive format requests.
    # Never infer an OR from AND, nor merge independent financing questions.
    grouped={k for g in data['alternatives'] for k in g['request_ids']}
    for left,lp in FORMATS.items():
        for right,rp in FORMATS.items():
            if left==right:continue
            match=re.search(r'\b'+lp+r'\s+or\s+(?:(?:a|the|some)\s+)?'+rp+r'\b',own,re.I)
            if not match or not re.search(r'\b(?:send|show|share|have|get|see)\b',own[:match.start()],re.I):continue
            rows=[r for r in data['requests'] if r['topic']=='materials' and r['polarity']=='request' and r['subject'] in {left,right} and r['evidence'] in own]
            if len(rows)!=2 or {r['subject'] for r in rows}!={left,right}:continue
            if any(r['id'] in grouped for r in rows) or rows[0]['reference_id']!=rows[1]['reference_id']:continue
            ids=[r['id'] for r in rows];key='literal_format_or'
            while any(g['id']==key for g in data['alternatives']):key+='x'
            data['alternatives'].append(dict(id=key,request_ids=ids,evidence=match.group()))
            data['all_of']=[k for k in data['all_of'] if k not in ids];grouped.update(ids)
            notes.append({'field':'alternatives','action':'literal_formats_are_alternatives','evidence':match.group(),'request_ids':ids})
    if not notes:return value,[]
    used={r['reference_id'] for r in data['requests']}|{c['reference_id'] for c in data['constraints']}|{data['selected_reference_id']}
    data['references']=[r for r in data['references'] if r['id'] in used]
    return Understanding.model_validate(data).check_evidence(text),notes
