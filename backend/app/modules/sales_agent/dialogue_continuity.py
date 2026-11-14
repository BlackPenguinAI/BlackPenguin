"""Bounded current-message continuations. Never grants booking or raises confidence."""
import re
from .understanding_contract import Understanding


def normalize(value,text,state,latest):
    from .reference_resolution import accepted
    if not latest or not accepted(latest):return value,[]
    data=value.model_dump(mode='json');notes=[];meta=latest.metadata_json or {}
    # Never override exclusions, multiple choices, third-party or conditional speech.
    if data['constraints'] or data['alternatives'] or data['releases'] or data['cancellation'] or data['reschedule'] or data['wait'] or data['moderation'] or any(r['polarity']=='exclude' for r in data['requests']):return value,[]
    if re.search(r"\b(?:not|never|don't|do not|if|suppose|friend|said|told)\b",text,re.I):return value,[]
    from .interpretation_consistency import POSITIVE_VISIT,EXISTING_QUERY
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    # A new visit has a property subject; '/' cannot select an appointment.
    # Rebind only this invalid marker, never a real slot or booking confirmation.
    invitation=bool(meta.get('visit_invitation') and not any(meta.get(k) for k in
        ('material_offer','appointment_offer','booking_confirmation','release_offer','location_offer')))
    short_reply=re.fullmatch(r"\s*(?:can|could) (?:I|we) (?:see|view) (it|this|that)(?: please)?[?! .]*",own,re.I)
    anaphor=re.search(r'\b(?:the|this|that) (property|home|house|unit)\b',own,re.I)
    target_evidence=anaphor.group() if anaphor else short_reply[1] if invitation and short_reply else None
    if (own==text and target_evidence and data['visit'] and data['visit']['action']=='request'
        and (POSITIVE_VISIT.search(own) or invitation and short_reply) and not EXISTING_QUERY.search(own)
        and not data['appointment_query'] and not data['comparison']):
        unit=bool(anaphor and anaphor[1].lower()=='unit')
        selected=state.selected_unit_id if unit else state.selected_property_type_id
        ids={r['reference_id'] for r in data['requests'] if r['topic']=='appointment' and r['polarity']=='request'}
        if selected:
            for ref in data['references']:
                if ref['id'] in ids and ref['kind']=='appointment' and ref['expression']=='/':
                    ref.update(kind='unit' if unit else 'property',expression='this unit' if unit else 'this property',evidence=target_evidence)
                    notes.append({'field':'references','action':'new_visit_placeholder_is_current_property_not_slot','evidence':target_evidence})
    # Conflicting read interpretations after a delivered in-person invitation
    # ask the lead; they never gain availability, sharing or booking authority.
    ambiguous=re.fullmatch(r"\s*(?:can|could) (?:I|we) (?:see|view) (?:it|this|that)(?: please)?[?! .]*",own,re.I)
    if (own==text and ambiguous and meta.get('visit_invitation')
        and not any(meta.get(k) for k in ('material_offer','appointment_offer','booking_confirmation','release_offer','location_offer'))
        and not data['visit'] and not data['appointment_query'] and not data['selected_reference_id']
        and all(r['topic'] in {'materials','catalog','property_details','other'} for r in data['requests'])):
        data.update(requests=[],all_of=[],references=[],selected_reference_id=None,comparison=None,
            requires_clarification=True,clarification_question='Do you mean viewing the property in person or seeing its photos?')
        notes.append({'field':'requests','action':'clarify_file_or_visit_after_delivered_visit_invitation','effect_authorization':False})
        return Understanding.model_validate(data).check_evidence(text),notes
    bedroom=re.fullmatch(r'\s*([1-6])(?:\s+bedrooms?)?[?.!]?\s*',text,re.I)
    if bedroom and ('bedroom' in text.lower() or meta.get('needs_search') and not meta.get('property_catalog_offer')) and not meta.get('appointment_offer'):
        data.update(requests=[dict(id='bedroom_continuation',topic='catalog',polarity='request',evidence=text)],all_of=['bedroom_continuation'],
            references=[],comparison=None,visit=None,selected_reference_id=None,requires_clarification=False,clarification_question=None,
            preferences=[dict(key='bedrooms',value=bedroom[1],evidence=text,status='declared')])
        notes.append({'field':'requests','action':'bedrooms_answer_to_current_needs_question'})
    choice=re.fullmatch(r"\s*(?:(?:Give me|Tell me) more (?:information|details) about )?(?:(?:the )?(?:property|option) )?([1-9][0-9]?)[.!]?\s*",text,re.I)
    if choice and meta.get('property_catalog_offer'):
        ids=meta['property_catalog_offer'].get('property_type_ids',[])
        if int(choice[1])<=len(ids):
            data.update(requests=[dict(id='current_choice',topic='property_details',polarity='request',evidence=text,reference_id='chosen_property')],all_of=['current_choice'],
                references=[dict(id='chosen_property',kind='property',expression='property '+choice[1],evidence=text)],comparison=None,visit=None,
                selected_reference_id='chosen_property',requires_clarification=False,clarification_question=None)
            notes.append({'field':'requests','action':'details_for_current_numbered_property'})
    # Scoped state owns the subject; the quote remains the current message.
    if state.selected_property_type_id:
        material=re.fullmatch(r'\s*(?:(?:do you have|(?:please )?(?:show|send)(?: me)?|I want to (?:check|see))\s+)(?:the (?:property )?)?(photos?|pictures?|images?|blueprints?|floor plans?)(?: of (?:the|this|that) property)?[?.!]?\s*',text,re.I)
        anaphor=re.search(r'\b(?:the|this|that) property\b',text,re.I)
        if material:
            subject='floor_plan' if re.search(r'blueprint|floor',material[1],re.I) else 'photos'
            data.update(requests=[dict(id='current_material',topic='materials',subject=subject,polarity='request',evidence=text,reference_id='current_owner')],all_of=['current_material'],
                references=[dict(id='current_owner',kind='property',expression='this property',evidence=text)],comparison=None,visit=None,
                selected_reference_id=None,requires_clarification=False,clarification_question=None)
            notes.append({'field':'references','action':'bind_single_material_request_to_active_subject'})
        elif anaphor:
            for ref in data['references']:
                if ref['kind']=='property' and ref['expression']=='/':
                    ref.update(expression=anaphor.group(),evidence=anaphor.group())
                    notes.append({'field':'references','action':'replace_placeholder_with_current_anaphor'})
    if state.selected_property_type_id and not data['comparison'] and not data['visit'] and len(data['requests'])==1 and data['requests'][0]['topic'] in {'catalog','property_details'} and re.search(r'\b(?:differ|differs|differences)\b',text,re.I) and re.search(r'\b(?:others|other options|other properties)\b',text,re.I) and re.search(r'\b(?:this|that|the) property\b',text,re.I):
        data.update(requests=[dict(id='current_comparison',topic='catalog',polarity='request',evidence=text)],all_of=['current_comparison'],references=[],
            comparison=dict(request_id='current_comparison',reference_ids=[],include_current=True,include_all=True,all_kind='property',criteria=['general'],operation='compare',evidence=text),
            visit=None,requires_clarification=False,clarification_question=None)
        notes.append({'field':'comparison','action':'compare_active_property_with_other_options'})
    # A copied sentence isn't a timezone/duration. Absent optional values stay absent.
    if data['visit'] and data['visit'].get('timing'):
        timing=data['visit']['timing']
        if timing.get('timezone_evidence') and not re.search(r'\b[A-Za-z_]+/[A-Za-z_]+|\b(?:timezone|time zone|local time|my time|UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b',text,re.I):
            timing['timezone_evidence']=None;notes.append({'field':'visit.timing.timezone_evidence','action':'omit_non_timezone_sentence'})
        if timing.get('duration_evidence') and not re.search(r'\b\d+\s*(?:minutes?|hours?|mins?|hrs?)\b',text,re.I):
            timing['duration_evidence']=None;notes.append({'field':'visit.timing.duration_evidence','action':'omit_undeclared_duration'})
    result=Understanding.model_validate(data).check_evidence(text)
    return result,notes


def catalog_choice_read(value,text,latest,commercial):
    """Only a bounded read of the exact numbered current offer; no effects."""
    from .reference_resolution import accepted
    if not latest or not accepted(latest):return False
    if ((latest.metadata_json or {}).get('delivery_group') or {}).get('total',1)>1:return False
    ids=((latest.metadata_json or {}).get('property_catalog_offer') or {}).get('property_type_ids',[])
    match=re.fullmatch(r"\s*(?:(?:Give me|Tell me) more (?:information|details) about )?(?:(?:the )?(?:property|option) )?([1-9][0-9]?)[.!]?\s*",text,re.I)
    if not match or int(match[1])>len(ids):return False
    if ids[int(match[1])-1] not in {p['id'] for p in commercial.get('property_types',[])}:return False
    if len(value.requests)!=1 or value.requests[0].id!='current_choice' or value.requests[0].topic.value!='property_details' or value.requests[0].polarity!='request':return False
    return not (value.constraints or value.alternatives or value.releases or value.comparison or any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query','personal_facts','preference_withdrawals','source_purposes','objections')))


def comparison_read(db,scope,value,text):
    """A literal comparison with all scoped subjects resolved permits reads only.

    Confidence is retained as model evidence. Restrictions and per-field tool
    permissions remain authoritative. This cannot authorize selection or effects.
    """
    from .reference_resolution import Resolver,accepted
    from .dialogue_store import load
    from .turn_context import latest_outbound
    if not re.search(r'\b(?:compare|comparison|differ|differs|differences)\b',text,re.I):return False
    if re.search(r"\b(?:not|never|don't|do not|if|suppose|friend|said|told)\b|[\"“”]",text,re.I):return False
    if not value.comparison or value.comparison.operation!='compare' or len(value.requests)!=1:return False
    if value.requests[0].topic.value!='catalog' or value.requests[0].polarity!='request':return False
    if value.constraints or value.alternatives or value.releases:return False
    if any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query','personal_facts','preference_withdrawals','source_purposes','objections')):return False
    latest=latest_outbound(db,scope.conversation_id)
    if not latest or not accepted(latest) or ((latest.metadata_json or {}).get('delivery_group') or {}).get('total',1)>1:return False
    _,state=load(db,scope);resolver=Resolver(db,scope,state)
    subjects=set()
    for reference in value.references:
        result=resolver.resolve(reference)
        if result['status']!='resolved' or result['value']['kind']!='property':return False
        subjects.add(result['value']['property_id'])
    if value.comparison.all_kind!='property':return False
    if value.comparison.include_all:subjects.update(resolver.types)
    if value.comparison.include_current:
        if not resolver.bound('property',state.selected_property_type_id):return False
        subjects.add(state.selected_property_type_id)
    return 2<=len(subjects)<=20


def literal_greeting(value,text):
    """Only social acknowledgement; no confidence promotion or action permission."""
    return bool(re.fullmatch(r"\s*(?:hi|hello|hey|good morning|good afternoon|good evening)[!.?]*\s*",text,re.I)
        and value.courtesy and value.courtesy.kind=='greeting'
        and all(r.topic.value=='other' and r.polarity=='request' for r in value.requests)
        and not any((value.visit,value.comparison,value.appointment_query,value.cancellation,value.reschedule,
                     value.wait,value.moderation,value.constraints,value.alternatives,value.releases,
                     value.preferences,value.personal_facts,value.preference_withdrawals,value.source_purposes,
                     value.references,value.selected_reference_id,value.objections,value.empathy)))
