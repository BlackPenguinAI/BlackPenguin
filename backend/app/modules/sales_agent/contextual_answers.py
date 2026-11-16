"""Current literal answers to the latest delivered question; no final consent inferred."""
import re
VERSION='sales-contextual-answers/1.0'

def repair(data,text,reply='',metadata=None):
    meta=metadata or {};topic=None;subject=None;target=None;courtesy=None;visit=None;prefs=[]
    count=re.fullmatch(r"\s*([1-9])(?: bedrooms?)?(?:[, ]+(?:it['’]?s|is|are))? (?:ok|okay|good|fine)(?: (?:for me|now))?[.!]?\s*",text,re.I)
    if count and 'bedrooms essential' in reply.lower():
        topic='catalog';prefs=[dict(key='bedrooms',value=count[1],evidence=text,status='declared')]
    elif re.fullmatch(r'\s*(?:financing|financing options)(?: (?:pls|please))?[.!?]?\s*',text,re.I):topic='financing'
    elif re.fullmatch(r'\s*(?:the )?(?:layout|distribution) of (?:the )?rooms[.!]?\s*',text,re.I) and 'what matters most' in reply.lower():topic='property_details'
    elif re.fullmatch(r'\s*(?:no(?:[, ]+(?:it[’\']?s ok|thanks))?|no[, ]+bye)[.!]?\s*',text,re.I) and ('another property question' in reply.lower() or 'what else would you like to know' in reply.lower() or re.search(r'\bbye\b',text,re.I)):
        courtesy=dict(kind='farewell',evidence=text)
    elif meta.get('appointment_offer') and (m:=re.fullmatch(r'\s*(?:option )?([1-9])(?: (?:it[’\']?s|is))?(?: ok for me)?[.!]?\s*',text,re.I)):
        topic='appointment';target=dict(kind='appointment',expression='option '+m[1],evidence=text);visit=dict(action='select',evidence=text,timing=None)
    elif meta.get('material_offer') and re.fullmatch(r'\s*(?:ok|okay|yes(?:[, ]+(?:please|share (?:it|me)))?|(?:please )?(?:send|share)(?: me)? (?:this |the )?(?:pdf|brochure|gallery|photos))[.!]?\s*',text,re.I):
        items=meta['material_offer'].get('items',[])
        explicit_pdf=bool(re.search(r'pdf|brochure',text,re.I))
        explicit_gallery=bool(re.search(r'gallery|photos',text,re.I))
        eligible=[i for i in items if
            (not explicit_pdf or i.get('binding',{}).get('mime_type')=='application/pdf') and
            (not explicit_gallery or i.get('binding',{}).get('type')=='gallery_image')]
        if len(eligible)==1:
            binding=eligible[0]['binding']
            topic='materials';subject='photos' if binding.get('type')=='gallery_image' else 'brochure' if binding.get('mime_type')=='application/pdf' else None
            target=dict(kind='material',expression=binding['name'],evidence=text)
    if not topic and not courtesy:return data,[]
    fixed={k:None if isinstance(v,dict) else [] if isinstance(v,list) else v for k,v in data.items()}
    fixed.update(requests=[dict(topic=topic,subject=subject,target=target,polarity='request',evidence=text)] if topic else [],preferences=prefs,visit=visit,courtesy=courtesy,selection=None,requires_clarification=False,clarification_question=None)
    return fixed,[dict(field='requests',action='latest_question_contextual_answer',evidence=text,effect_authorization=False,confidence_unchanged=data['confidence'])]

def authorized(value,text,reply,metadata):
    expected,notes=repair({'confidence':value.confidence},text,reply,metadata)
    if not notes or value.constraints or value.releases or value.alternatives or value.comparison:return False
    if any(getattr(value,k) for k in ('cancellation','reschedule','wait','moderation','appointment_query','personal_facts','preference_withdrawals','source_purposes','objections')):return False
    return ([(r.topic.value,r.polarity) for r in value.requests]==[(r['topic'],'request') for r in expected['requests']] and
            (value.visit.action if value.visit else None)==(expected.get('visit') or {}).get('action') and
            (value.courtesy.kind if value.courtesy else None)==(expected.get('courtesy') or {}).get('kind'))
