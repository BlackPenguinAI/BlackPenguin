"""Current explicit subjects and first-visit meaning; never final booking consent."""
import re
from .understanding_contract import Understanding

POSITIVE_VISIT=re.compile(r"\b(?:I (?:would like|want|need)(?: to)?|I['’]d like to|please|(?:can|could) (?:I|we))[^.!?\n]{0,80}\b(?:(?:arrange|book|schedule|organize|have)[^.!?\n]{0,60}\b(?:in[ -]person )?(?:visit|viewing|appointment)|visit)\b",re.I)
NEGATIVE=re.compile(r"\b(?:not|never|don't|don’t|do not|if|suppose|friend|said|says|told|he|she|they)\b",re.I)
EXISTING_QUERY=re.compile(r'\b(?:do I have|my (?:current|existing|upcoming|past) (?:visits|appointments)|what (?:visits|appointments) (?:do I|have I)|show (?:me )?my (?:visits|appointments))\b',re.I)
DECLINE=re.compile(r"\b(?:I do not want a visit yet|I don['’]t want a visit yet|I['’]m not ready for a visit|no visit for now)\b",re.I)


def normalize(value,text,commercial,*,appointment_offer=None):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    from .needs_search import normalize as normalize_needs
    value,notes=normalize_needs(value,text,commercial)
    data=value.model_dump(mode='json')
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
    literal_names=named(own)
    if (len(literal_names)==1 and own.strip().rstrip('.!').casefold()==literal_names[0].casefold()
        and not data['constraints'] and not data['alternatives'] and not data['releases']
        and not data['cancellation'] and not data['reschedule'] and not data['wait']):
        key=reference(literal_names[0])
        data.update(requests=[dict(id='named_information',topic='catalog',subject=None,polarity='request',evidence=text,reference_id=key)],all_of=['named_information'],
            references=[r for r in data['references'] if r['id']==key],selected_reference_id=key,
            comparison=None,visit=None,appointment_query=None)
        value=Understanding.model_validate(data).check_evidence(text)
        notes.append({'field':'requests','action':'named_property_is_selection_not_comparison'})
    choice=re.fullmatch(r"\s*(?:Actually[, ]+)?(?:I (?:prefer|choose|want|would like)|I['’]d (?:like|prefer)|I['’]ll take) (.+?)(?: instead)?[.!]?\s*",own,re.I)
    if (choice and own==text and len(named(choice[1]))==1 and choice[1].strip().rstrip('.!').casefold()==named(choice[1])[0].casefold()
        and not data['constraints'] and not data['alternatives'] and not data['releases'] and not data['preference_withdrawals']
        and not data['visit'] and not data['cancellation'] and not data['reschedule'] and not data['wait'] and not data['appointment_query']):
        name=named(choice[1])[0];key=reference(name)
        data.update(requests=[dict(id='explicit_property_choice',topic='catalog',subject=None,polarity='request',evidence=text,reference_id=key)],all_of=['explicit_property_choice'],
            references=[r for r in data['references'] if r['id']==key],selected_reference_id=key,comparison=None)
        notes.append({'field':'requests','action':'explicit_preference_changes_active_subject','evidence':name})
    # A current explicit choice can own an anaphoric material request in the
    # next clause. No historical subject, model ID or confidence is promoted.
    switch=re.fullmatch(
        r"\s*(?:Actually[, ]+)?(?:I (?:prefer|choose|want|would like)|I['’]d like|I['’]ll take) "
        r"(?P<owner>.+?)(?: instead)?[.!]\s*"
        r"(?P<request>(?:(?:Please|Could you|Can you) )?(?:send|show)(?: me)? "
        r"(?:its|that property's|this property's|the property's) "
        r"(?P<subject>photos?|pictures?|images?|brochure(?: PDF)?|PDF|floor plan)(?: please)?[.!?]?)\s*",own,re.I)
    if (switch and own==text and not data['alternatives'] and not data['constraints']
        and not data['comparison'] and not data['cancellation'] and not data['reschedule']
        and not data['wait'] and not data['releases'] and not data['preference_withdrawals']
        and not data['appointment_query'] and len(data['requests'])==1):
        candidates=named(switch['owner']);row=data['requests'][0]
        if (len(candidates)==1 and switch['owner'].casefold()==candidates[0].casefold()
            and row['topic']=='materials' and row['polarity']=='request'):
            key=reference(candidates[0]);tag=switch['subject'].casefold()
            subject='brochure' if 'pdf' in tag or 'brochure' in tag else 'floor_plan' if 'floor' in tag else 'photos'
            # A conflicting requested format must be repaired by the model.
            if row['subject'] in {None,subject}:
                row.update(reference_id=key,subject=subject,evidence=switch['request'])
                data['references']=[r for r in data['references'] if r['id']==key]
                data['selected_reference_id']=key
                data['visit']=None
                result=Understanding.model_validate(data).check_evidence(text)
                if result==value:return value,[]
                return result,[{'field':'references','action':'bind_anaphoric_material_to_explicit_current_choice',
                    'choice_evidence':candidates[0],'request_evidence':switch['request'],
                    'confidence_unchanged':value.confidence}]
    # Only a complete backend-rendered choice grants selection, never booking.
    from .first_booking import contextual_public_selection
    chosen=contextual_public_selection(own,appointment_offer)
    if chosen and own==text and not data['alternatives']:
        index=next(i for i,o in enumerate(appointment_offer['options']) if o['starts_at']==chosen['id'])
        expression=('first','second','third')[index]+' appointment'
        data.update(requests=[dict(id='public_slot',topic='appointment',subject=None,polarity='request',evidence=text,reference_id='public_slot_ref')],
            all_of=['public_slot'],references=[dict(id='public_slot_ref',kind='appointment',expression=expression,evidence=text)],
            comparison=None,visit=dict(action='select',evidence=text,timing=None),appointment_query=None,
            selected_reference_id=None,requires_clarification=False,clarification_question=None,cancellation=None,reschedule=None)
        data['preferences']=[p for p in data['preferences'] if p['key']!='visit_readiness']
        result=Understanding.model_validate(data).check_evidence(text)
        return result,[{'field':'visit','action':'select_exact_backend_public_option','evidence':text}]
    # Looking at a named property is information consent, not visit consent.
    if data['visit'] and data['visit']['action']=='request':
        quote=data['visit']['evidence']
        show=re.fullmatch(r'(?:Please )?(?:show|tell) me (?:about )?(.+?)[.!]?',quote,re.I)
        if show and quote in own and len(named(show[1]))==1 and show[1].rstrip('.!').casefold()==named(show[1])[0].casefold():
            data['visit']=None
            notes.append({'field':'visit','action':'property_information_is_not_visit_consent','evidence':quote})
    # Recover only a single, literal material instruction, not a mixed question.
    material=re.fullmatch(r"\s*(?:Please )?(?:send|show)(?: me)? (?:the )?(brochure(?: PDF)?|PDF|photos?|pictures?|images?|floor plan) (?:for|of) (.+?)[.!]?\s*",own,re.I)
    if material and own==text and not data['alternatives'] and not data['constraints']:
        candidates=named(material[2])
        if len(candidates)==1 and material[2].rstrip('.!').casefold()==candidates[0].casefold():
            tag=material[1].casefold()
            subject='brochure' if 'pdf' in tag or 'brochure' in tag else 'floor_plan' if 'floor' in tag else 'photos'
            data.update(requests=[dict(id='explicit_material',topic='materials',subject=subject,polarity='request',evidence=text,reference_id=reference(candidates[0]))],
                all_of=['explicit_material'],comparison=None,visit=None,appointment_query=None,selected_reference_id=None,
                requires_clarification=False,clarification_question=None,cancellation=None,reschedule=None)
            result=Understanding.model_validate(data).check_evidence(text)
            if result==value:return value,[]
            return result,[{'field':'requests','action':'preserve_literal_single_material_request','evidence':text}]
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
            comparison=data['comparison']
            pure_visit=bool(POSITIVE_VISIT.match(own.strip())) or all(POSITIVE_VISIT.search(q) or re.fullmatch(r'Any (?:available )?time in the next (?:seven|7) days works for me[.!]?',q,re.I) or re.fullmatch(r'Please use the project timezone[.!]?',q,re.I) for q in clauses)
            from .understanding_semantics import COMPARATIVE_SIGNAL
            if comparison and pure_visit and not re.search(COMPARATIVE_SIGNAL,own,re.I):
                key=comparison['request_id']
                data['requests']=[r for r in data['requests'] if r['id']!=key]
                data['all_of']=[k for k in data['all_of'] if k!=key]
                data['comparison']=None
                notes.append({'field':'comparison','action':'omit_comparison_invented_from_pure_visit','evidence':quote})
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
                # A date phrase copied into a clock field is not a local hour.
                # Recover only explicit flexibility with identical current date
                # evidence and no actual clock restriction; keep all real times.
                if (timing and timing.get('time_relation')=='any'
                    and re.search(r'\bany (?:available )?time\b',own,re.I)
                    and not re.search(r'\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:am|pm)\b|\b(?:after|before|between|morning|afternoon|evening)\b',own,re.I)):
                    dates={timing.get(k) for k in ('date_from_evidence','date_until_evidence') if timing.get(k)}
                    for key in ('time_from_evidence','time_until_evidence'):
                        evidence=timing.get(key)
                        if evidence in dates and evidence in own and re.fullmatch(r'(?:the )?next (?:seven|7) days',evidence,re.I):
                            timing[key]=None
                            notes.append({'field':'visit.timing.'+key,'action':'omit_date_phrase_from_flexible_clock','evidence':evidence})
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
