"""Defensive vetoes, not a replacement for structured LLM interpretation."""
import re
from app.modules.governance.services import request_attribution

TERMS = {
    'appointment':r'visits?|appointments?|schedule|book|visitas?|citas?|agendar',
    'photos':r'photos?|pictures?|images?|fotos?|im[aá]genes?',
    'brochure':r'brochures?|folletos?',
}


def prohibited(text, topic):
    current = request_attribution(text or '')['current_text']
    pattern = TERMS.get(topic, re.escape(topic))
    negative = False
    for clause in re.split(r'[.!?;\n]|\b(?:but|however|pero|sin embargo|actually)\b',current,flags=re.I):
        if re.search(rf"\b(?:no|not|never|don't|do not|sin|avoid)\b[^.!?;\n]{{0,80}}\b(?:{pattern})\b",clause,re.I):
            negative = True
        elif re.search(r'\b(?:want|please|send|book|quiero|env[ií]a|agendar)\b',clause,re.I) and re.search(rf'\b(?:{pattern})\b',clause,re.I):
            negative = False
    return negative


def explicit_reversal(evidence):
    return bool(re.search(r'\b(?:changed my mind|actually|now|ahora|cambi[eé] de opini[oó]n|s[ií] quiero)\b',evidence,re.I))


def apply_vetoes(understanding, text):
    from .understanding_contract import Constraint
    constraints=list(understanding.constraints)
    for topic,subject,key in [('appointment',None,'appointment'),('materials','photos','photos'),('materials','brochure','brochure')]:
        if prohibited(text,key):
            constraint=Constraint(topic=topic,subject=subject,scope='until_explicit_change' if topic=='appointment' else 'turn',evidence=text[:2000])
            if constraint not in constraints:constraints.append(constraint)
    return understanding.model_copy(update={'constraints':constraints})
