"""Bounded literal read repair before historical reference evidence is compiled."""
import re

def literal_material(data,text):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    pattern=(r'\s*(?:(?:Before (?:choosing|picking|selecting) (?:a |the )?(?:time|slot)|First),\s*)?'
        r'(?:(?:can|could|would) you (?:show|send|share)(?: me| us)?|(?:please )?(?:show|send|share)(?: me| us)?|do you have)\s+'
        r'(?:the (?:property )?)?(photos?|pictures?|images?|blueprints?|floor plans?|brochure|PDF)'
        r'(?: of (?:the|this|that) property)?(?: please)?[?.!]?\s*')
    match=re.fullmatch(pattern,own,re.I)
    if own!=text or not match:return data,[]
    if any(data.get(k) for k in ('constraints','alternatives','releases','cancellation','reschedule','wait','moderation','appointment_query')):return data,[]
    rows=data.get('requests') or []
    if not any(r.get('topic')=='comparison' for r in rows):return data,[]
    if any(r.get('polarity')!='request' or r.get('topic') not in {'comparison','materials','catalog','property_details','other','appointment'} for r in rows):return data,[]
    # Exact grammar proves a read request, never consent for any appointment.
    subject='floor_plan' if re.search(r'floor|blueprint',match[1],re.I) else 'brochure' if re.search(r'pdf|brochure',match[1],re.I) else 'photos'
    fixed={**data,'requests':[dict(topic='materials',polarity='request',subject=subject,evidence=text,target=None)],
        'selection':None,'visit':None,'requires_clarification':False,'clarification_question':None}
    return fixed,[{'field':'requests','action':'literal_material_read_not_comparison','evidence':text,'subject':subject,'confidence_unchanged':data['confidence']}]
