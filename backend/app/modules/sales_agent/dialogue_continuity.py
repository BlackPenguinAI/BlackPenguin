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
    # A pronoun following a material offer refers to that offer, not to a new
    # property choice. Multiple files require a focused choice, never a guess.
    if (own==text and ambiguous and (meta.get('material_offer') or {}).get('items') and
        not any(meta.get(k) for k in ('visit_invitation','appointment_offer','booking_confirmation','release_offer','location_offer')) and
        not data['visit'] and not data['appointment_query'] and not data['comparison'] and
        all(r['topic'] in {'materials','catalog','property_details','other'} for r in data['requests']) and
        (meta.get('delivery_group') or {}).get('total',1)==1):
        items=meta['material_offer'].get('items') or []
        if len(items)==1 and items[0].get('binding',{}).get('name'):
            data.update(requests=[dict(id='offered_material',topic='materials',polarity='request',evidence=text,reference_id='offered_file')],all_of=['offered_material'],
                references=[dict(id='offered_file',kind='material',expression=items[0]['binding']['name'],evidence=text)],
                selected_reference_id=None,requires_clarification=False,clarification_question=None)
        else:
            data.update(requests=[],all_of=[],references=[],selected_reference_id=None,
                requires_clarification=True,clarification_question='Which of the materials I offered would you like to see?')
        notes.append({'field':'references','action':'pronoun_continues_delivered_material_offer','confidence_unchanged':value.confidence})
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
        material=re.fullmatch(r'\s*(?:(?:do you have|(?:can|could|would) you (?:show|send)(?: me| us)?|(?:please )?(?:show|send)(?: me| us)?|(?:I|we) (?:want|would like|need) to (?:check|see|view))\s+)(?:the (?:property )?)?(photos?|pictures?|images?|blueprints?|floor plans?)(?: of (?:the|this|that) property)?[?.!]?\s*',text,re.I)
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


def named_choice_read(value,text,latest,commercial):
    """Read details for an exact name in the complete last public offer only."""
    from .reference_resolution import accepted
    if not latest or not accepted(latest):return False
    meta=latest.metadata_json or {}
    if (meta.get('delivery_group') or {}).get('total',1)>1:return False
    ids=(meta.get('property_catalog_offer') or {}).get('property_type_ids',[])
    matches=[r for r in commercial.get('property_types',[]) if r.get('id') in ids and
             str(r.get('property_type','')).strip().casefold()==text.strip().rstrip('.!').casefold()]
    if len(matches)!=1 or not matches[0].get('property_type'):return False
    if value.requires_clarification or value.constraints or value.alternatives or value.releases or value.comparison:return False
    if any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query')):return False
    if len(value.requests)!=1:return False
    row=value.requests[0]
    ref=next((r for r in value.references if r.id==row.reference_id),None)
    return bool(row.topic.value in {'catalog','property_details'} and row.polarity=='request' and
                ref and ref.kind=='property' and ref.expression.casefold()==matches[0]['property_type'].casefold())


def focused_visit_question(value,text,commercial):
    """Ask for search permission without raising confidence or granting effects."""
    from .interpretation_consistency import POSITIVE_VISIT,EXISTING_QUERY
    from app.modules.governance.services import request_attribution
    if request_attribution(text)['current_text']!=text or REPORTED_VISIT.search(text) or EXISTING_QUERY.search(text):return None
    if not value.visit or value.visit.action!='request' or value.visit.timing:return None
    if not (POSITIVE_VISIT.search(text) or re.search(r'\bin[- ]person (?:visit|viewing)\b|\b(?:I|we) (?:would like|want|need) to (?:visit|view)\b',text,re.I)):return None
    if value.constraints or value.alternatives or value.releases or value.comparison:return None
    if any(getattr(value,k) for k in ('reschedule','cancellation','wait','moderation','appointment_query')):return None
    if len(value.requests)!=1 or not value.permits('appointment'):return None
    ref=next((r for r in value.references if r.id==value.requests[0].reference_id),None)
    if not ref or ref.kind!='property':return None
    matches=[r for r in commercial.get('property_types',[]) if r.get('property_type') and
             ref.expression.casefold()==r['property_type'].casefold() and r['property_type'].casefold() in text.casefold()]
    if len(matches)!=1:return None
    others=[r.get('property_type') for r in commercial.get('property_types',[]) if r.get('property_type')!=matches[0]['property_type']]
    if any(name and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I) for name in others):return None
    return 'Would you like me to check available visit times for '+matches[0]['property_type']+'?'


REPORTED_VISIT=re.compile(r"\b(?:not|never|don.t|do not|if|suppose|friend|said|told|already|previous|yesterday)\b|[\"“”]",re.I)


def literal_material_read(db,scope,value,text):
    """A literal request + approved current owner allows discovery, not booking.

    Sharing still passes material approval, coverage, restrictions and delivery
    checks. Model confidence remains untouched; this is a scoped capability.
    """
    from .dialogue_store import load
    from .reference_resolution import Resolver
    from app.modules.governance.services import request_attribution
    if request_attribution(text)['current_text']!=text:return False
    if value.comparison or value.constraints or value.alternatives or value.releases:return False
    if any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query','preferences','personal_facts','preference_withdrawals','source_purposes','objections')):return False
    if len(value.requests)!=1:return False
    row=value.requests[0]
    if row.id=='explicit_material' and row.topic.value=='materials' and row.polarity=='request' and row.evidence==text:
        from app.modules.projects.models import Project
        from .commercial_context import build_commercial_context
        from .literal_material import named_request
        from .dialogue_store import check_scope
        conversation=check_scope(db,scope)
        commercial=build_commercial_context(db,project=db.get(Project,scope.project_id),company_id=scope.company_id,lead_id=scope.lead_id,channel=conversation.channel)
        target=named_request(text,commercial)
        ref=next((r for r in value.references if r.id==row.reference_id),None)
        if not target or not target['property_id'] or not ref or len(value.references)!=1 or ref.kind!='property' or row.subject!=target['subject']:return False
        _,state=load(db,scope)
        result=Resolver(db,scope,state).resolve(ref)
        return bool(result.get('status')=='resolved' and result['value'].get('property_id')==target['property_id'] and not result['value'].get('unit_id'))
    if row.id!='current_material' or row.topic.value!='materials' or row.polarity!='request':return False
    if row.evidence!=text or row.subject not in {'photos','floor_plan'}:return False
    ref=next((r for r in value.references if r.id==row.reference_id),None)
    if not ref or ref.kind!='property' or ref.expression!='this property':return False
    _,state=load(db,scope)
    if not state.selected_property_type_id or state.selected_unit_id:return False
    resolver=Resolver(db,scope,state);result=resolver.resolve(ref)
    return bool(result.get('status')=='resolved' and result['value'].get('property_id')==state.selected_property_type_id)


def focused_material_question(value,text,state,commercial):
    """A request-shaped material frame may ask a focused question, never share."""
    from app.modules.governance.services import request_attribution
    if request_attribution(text)['current_text']!=text or REPORTED_VISIT.search(text):return None
    if value.comparison or value.constraints or value.alternatives or value.releases:return None
    if any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query')):return None
    if len(value.requests)!=1 or not value.permits('materials'):return None
    subject=value.requests[0].subject
    labels={'photos':'photos','floor_plan':'the floor plan','brochure':'the brochure'}
    owners=[p for p in commercial.get('property_types',[]) if p.get('id')==state.selected_property_type_id]
    if subject not in labels or len(owners)!=1 or state.selected_unit_id:return None
    name=owners[0]['property_type']
    # A conflicting named reference needs reference resolution, not a presumed owner.
    if any(ref.kind not in {'property','material'} or ref.kind=='property' and
           ref.expression.casefold() not in {name.casefold(),'this property','the property','that property'} for ref in value.references):return None
    return 'Would you like '+labels[subject]+' of '+name+'?'


def mixed_material_financing_read(db,scope,value,text):
    """Exact independent reads for a resolved active owner, never visit consent."""
    from app.modules.governance.services import request_attribution
    from .dialogue_store import load
    from .reference_resolution import Resolver
    pattern=(r"\s*(?:(?:can|could|would) you |please )?(?:send|show|share)(?: me| us)? "
             r"(?:the )?(?:photos|pictures|images) or (?:a |the )?(?:brochure|PDF) "
             r"and (?:explain|describe) (?:the )?(?:financing|payment) options[?.!]?\s*")
    if request_attribution(text)['current_text']!=text or not re.fullmatch(pattern,text,re.I):return False
    if any(getattr(value,k) for k in ('comparison','constraints','releases','visit','reschedule','cancellation','wait','moderation','appointment_query','preferences','personal_facts','preference_withdrawals','source_purposes','objections')):return False
    if len(value.requests)!=3 or len(value.alternatives)!=1:return False
    materials=[q for q in value.requests if q.topic.value=='materials' and q.polarity=='request']
    finance=[q for q in value.requests if q.topic.value=='financing' and q.polarity=='request']
    if len(materials)!=2 or {q.subject for q in materials}!={'photos','brochure'} or len(finance)!=1:return False
    if set(value.alternatives[0].request_ids)!={q.id for q in materials} or set(value.all_of)!={finance[0].id}:return False
    if any(q.reference_id or not q.evidence or q.evidence not in text for q in value.requests) or value.references:return False
    _,state=load(db,scope)
    return bool(not state.selected_unit_id and Resolver(db,scope,state).bound('property',state.selected_property_type_id))
