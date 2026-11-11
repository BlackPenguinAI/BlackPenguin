"""Current explicit subjects and first-visit meaning; never final booking consent."""
import re
from .understanding_contract import Understanding

POSITIVE_VISIT=re.compile(r"\b(?:I (?:would like|want|need)(?: to)?|I['’]d like to|please|can (?:I|we))[^.!?\n]{0,80}\b(?:arrange|book|schedule|organize|have)[^.!?\n]{0,60}\b(?:in[ -]person )?(?:visit|viewing|appointment)\b",re.I)
NEGATIVE=re.compile(r"\b(?:not|never|don't|don’t|do not|if|suppose|friend|said|says|told|he|she|they)\b",re.I)
EXISTING_QUERY=re.compile(r'\b(?:do I have|my (?:current|existing|upcoming|past) (?:visits|appointments)|what (?:visits|appointments) (?:do I|have I)|show (?:me )?my (?:visits|appointments))\b',re.I)
DECLINE=re.compile(r"\b(?:I do not want a visit yet|I don['’]t want a visit yet|I['’]m not ready for a visit|no visit for now)\b",re.I)


def normalize(value,text,commercial):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text'];data=value.model_dump(mode='json');notes=[]
    names=[r.get('property_type') for r in commercial.get('property_types',[])]
    def named(quote):
        matches=[]
        for name in set(n for n in names if isinstance(n,str) and len(n)>=3):
            if names.count(name)!=1:continue
            match=re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',quote,re.I)
            if match:matches.append(match.group())
        return matches
    def reference(name):
        found=next((r['id'] for r in data['references'] if r['kind']=='property' and r['expression'].casefold()==name.casefold() and r['id']),None)
        if found:return found
        key='current_subject';ids={r['id'] for r in data['references']}
        while key in ids:key+='x'
        data['references'].append(dict(id=key,kind='property',expression=name,evidence=name));return key
    for row in data['requests']:
        if row['topic']!='materials' or row['polarity']!='request' or row['evidence'] not in own or NEGATIVE.search(row['evidence']):continue
        candidates=named(row['evidence'])
        if len(candidates)==1:
            source=next((r for r in data['references'] if r['id']==row['reference_id']),None)
            if source is None or source['kind']=='material':
                row['reference_id']=reference(candidates[0]);notes.append({'field':'references','action':'bind_material_owner_from_exact_current_property','evidence':candidates[0]})
        if row['subject'] is None:
            tags=[]
            for subject,pattern in [('photos',r'\b(?:photos?|pictures?|images?)\b'),('brochure',r'\b(?:brochure|pdf)\b'),('floor_plan',r'\bfloor plans?\b')]:
                if re.search(pattern,row['evidence'],re.I):tags.append(subject)
            if len(tags)==1:
                row['subject']=tags[0];notes.append({'field':'subject','action':'preserve_explicit_material_subject','subject':tags[0]})
    # Restrict recovery to a literal affirmative NEW visit. Existing changes,
    # reported speech and mixed existing-appointment questions remain untouched.
    clauses=[m.group().strip() for m in re.finditer(r'[^.!?\n]+[.!?]?',own)]
    quote=next((q for q in clauses if POSITIVE_VISIT.search(q) and not NEGATIVE.search(q)),None)
    changes=re.search(r'\b(?:cancel|reschedul\w*|change my|move my)\b',own,re.I)
    if quote and not DECLINE.search(own) and len(named(quote))<=1 and not data['alternatives'] and not changes and not EXISTING_QUERY.search(own) and not value.requires_clarification:
        if not data['cancellation'] and not data['reschedule']:
            if data['appointment_query'] is not None:
                data['appointment_query']=None;notes.append({'field':'appointment_query','action':'new_visit_is_not_existing_appointment_query','evidence':quote})
            rows=[r for r in data['requests'] if r['topic']=='appointment' and r['polarity']=='request']
            if not rows:
                key='current_visit';ids={r['id'] for r in data['requests']}
                while key in ids:key+='x'
                candidates=named(quote)
                data['requests'].append(dict(id=key,topic='appointment',subject=None,polarity='request',evidence=quote,reference_id=reference(candidates[0]) if len(candidates)==1 else None))
                data['all_of'].append(key);notes.append({'field':'requests','action':'preserve_explicit_new_visit_request','evidence':quote})
            if data['visit'] is None:
                data['visit']=dict(action='request',evidence=quote,timing=None);notes.append({'field':'visit','action':'preserve_explicit_new_visit_directive','evidence':quote})
            if data['visit'] and data['visit']['action']=='request':
                timing=data['visit'].get('timing')
                if timing and re.search(r'\bany (?:available )?time\b',own,re.I) and not timing.get('time_from_evidence') and not timing.get('time_until_evidence') and timing.get('time_relation')!='any':
                    timing['time_relation']='any';notes.append({'field':'visit.timing.time_relation','action':'any_time_is_not_a_clock_range'})
    decline=DECLINE.search(own)
    if decline and not quote and not data['alternatives'] and not value.requires_clarification and not changes and not EXISTING_QUERY.search(own):
        # A refusal of a proposed visit does not cancel an existing booking.
        data.update(cancellation=None,reschedule=None,appointment_query=None,visit=dict(action='decline',evidence=decline.group(),timing=None))
        for row in data['requests']:
            if row['topic']=='appointment' and row['polarity']=='request' and DECLINE.search(row['evidence']):
                # Do not rewrite linked OR/comparison groups; ambiguity stays closed.
                if any(row['id'] in g['request_ids'] for g in data['alternatives']):continue
                row['polarity']='exclude';data['all_of']=[key for key in data['all_of'] if key!=row['id']]
        if not any(c['topic']=='appointment' for c in data['constraints']):
            data['constraints'].append(dict(topic='appointment',subject=None,effect='prohibit',scope='until_explicit_change',evidence=decline.group(),reference_id=None))
        notes.append({'field':'visit','action':'declining_a_visit_is_not_cancellation','evidence':decline.group()})
    if not notes:return value,[]
    return Understanding.model_validate(data).check_evidence(text),notes
