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


def literal_visit(data,text):
    """Recover only a complete, own visit request, never selection/confirmation.

    The target is quoted from this message, not taken from model comparisons.
    Unknown names still go through scoped reference resolution and clarification.
    """
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    pattern=(r'\s*(?:(?:Fine|Great|Thanks|Thank you|Okay|OK)[,.!]\s*)?'
        r'(?:(?:can|could) (?:I|we) (?:visit|view)|'
        r'(?:I|we) (?:want|would like|need) to (?:visit|view)|'
        r'(?:please )?(?:arrange|schedule|organize|book) (?:a |an )?(?:visit|viewing))'
        r'(?:\s+(?:to\s+)?(?P<owner>[^.!?;\n]+?))?[.!?]?\s*')
    match=re.fullmatch(pattern,own,re.I)
    if own!=text or not match:return data,[]
    owner=(match['owner'] or '').strip()
    if re.search(r"\b(?:not|never|no|don['’]t|if|suppose|friend|said|told|or|and|compare|versus|instead|tomorrow|today|next|at|before|after|cancel|reschedule)\b|\d{1,2}:\d{2}",owner,re.I):return data,[]
    if any(data.get(k) for k in ('constraints','releases','cancellation','reschedule','wait','moderation','appointment_query','personal_facts','preference_withdrawals','source_purposes','objections')):return data,[]
    rows=[*data.get('requests',[]),*[r for group in data.get('alternatives',[]) for r in group['requests']]]
    if not any(r.get('topic')=='comparison' for r in rows):return data,[]
    if any(r.get('polarity')!='request' or r.get('topic') not in {'comparison','appointment','other'} for r in rows):return data,[]
    target=None if not owner or re.fullmatch(r'(?:it|(?:the|this|that) (?:property|home|house|unit))',owner,re.I) else dict(kind='property',expression=owner,evidence=owner)
    fixed={**data,'requests':[dict(topic='appointment',polarity='request',evidence=text,target=target)],
        'alternatives':[],'selection':None,'comparison':None,
        'visit':dict(action='request',evidence=text,timing=None),'requires_clarification':False,'clarification_question':None}
    fixed.pop('comparison',None)  # Not part of the wire Input schema.
    return fixed,[{'field':'requests','action':'literal_visit_not_comparison','evidence':text,'confidence_unchanged':data['confidence'],'effect_authorization':False}]
