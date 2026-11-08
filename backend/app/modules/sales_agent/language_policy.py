"""English-only gate. Language is not intent, consent, or a reason to pause."""
from dataclasses import asdict, dataclass
from functools import lru_cache
import re

VERSION='sales-language-policy/1.0'
REENTRY='This conversation is currently available in English. Please re-enter your question in English.'
OUTPUT_FALLBACK='I could not prepare a verified English response yet. I can continue helping in English. Which property would you like to discuss?'
# Short English/property vocabulary avoids the documented short-text ambiguity
# of statistical language detection. It never chooses a commercial action.
ENGLISH=set('''a an the i you we me my your our it its they their this that these those
am is are was were be been being do does did have has had can could would should will
may might must please thanks thank hello hi hey yes no okay ok sure not dont dont want
need like looking look for to of in on at by from with about and or but if what which
who where when why how more most other another first second third next last one two
three four five bedroom bedrooms bathroom bathrooms bed beds home homes house houses
property properties apartment apartments condo condos unit units residence residences
studio studios loft lofts penthouse available availability information info details detail
price prices pricing cost costs budget range currency cash bank financing mortgage loan
payment payments deposit buy buying purchase purchasing rent rental investment investor
primary second residence move moving delivery completion date dates time times day days
week weeks month months year years today tomorrow yesterday monday tuesday wednesday
thursday friday saturday sunday morning afternoon evening am pm utc gmt usd cad mxn pen
eur dollars photos photo pictures picture images image brochure pdf plans plan floor
layout layouts amenities features feature finishes parking balcony garden pool location
address area size sizes square feet meters visit visits appointment appointments showing
tour tours schedule scheduled book booking confirm confirmation reschedule cancel keep
change changing compare comparison compare explain tell give send show share see view
get know find receive receiving speak talk human advisor sales representative help clear
any questions question only also all both either without yet already still again back
later now then before after good great sounds nice interested interest ready prefer
preferably considering consider within between around near close useful practical fit
fits family bigger smaller larger small big beautiful elaborate elaborate understand
learn clarification clarify want wanted looking incorrect wrong disagree expensive cheap
too very much many few less just actually instead sorry nothing something anything
everything whenever wherever currently verified approved recorded new old previous
open closed sent delivered read received unavailable unconfirmed until into around
howdy goodbye bye bye-bye stop unsubscribe end quit yes absolutely fine details don'''.split())


@dataclass(frozen=True)
class Decision:
    language:str
    confidence:float|None
    source:str
    needs_reentry:bool
    version:str=VERSION

    def metadata(self):return asdict(self)


class LanguageHold(Exception):
    def __init__(self,decision,*,output=False):
        self.decision,self.output=decision,output
        super().__init__('English-only policy requires a safe response.')


@lru_cache(maxsize=1)
def factory():
    from langdetect.detector_factory import DetectorFactory,PROFILES_DIRECTORY
    value=DetectorFactory();value.seed=0;value.load_profile(PROFILES_DIRECTORY)
    return value


def detect(text,*,names=(),contextual_answer=False,output=False):
    text=(text or '').strip()
    if not output and any(text.casefold()==str(name).strip().casefold() for name in names if name):
        return Decision('neutral',None,'exact_scoped_name',False)
    if contextual_answer and text.casefold() in {'sí','si','oui','sim'}:
        return Decision('neutral',None,'bounded_contextual_assent',False)
    sample=re.sub(r'https?://\S+',' ',text)
    if output:
        for name in sorted({str(n) for n in names if n and len(str(n))>=2},key=len,reverse=True):
            sample=re.sub(r'(?<!\w)'+re.escape(name)+r'(?!\w)',' ',sample,flags=re.I)
    tokens=re.findall(r'[^\W\d_]+',sample.casefold().replace('’',"'"),flags=re.UNICODE)
    if not tokens:return Decision('neutral',None,'number_time_or_symbol',False)
    if all(t in ENGLISH or len(t)==1 and t.isascii() for t in tokens):
        return Decision('en',1.0,'english_lexical_short_text',False)
    try:
        detector=factory().create();detector.append(sample[:6000])
        scores=detector.get_probabilities()
        top=scores[0]
        # Clear non-English clauses in otherwise mixed input remain gated.
        if not output:
            for clause in re.split(r'[,;!?\n]',sample):
                words=re.findall(r'[^\W\d_]+',clause.casefold(),flags=re.UNICODE)
                if len(words)>=2 and sum(w in ENGLISH for w in words)/len(words)<.5:
                    part=factory().create();part.append(clause)
                    result=part.get_probabilities()[0]
                    if result.lang!='en' and result.prob>=.90:
                        return Decision(result.lang,round(result.prob,6),'non_english_clause',True)
        accepted=top.lang=='en' and top.prob>=.55
        return Decision(top.lang,round(top.prob,6),'statistical_local',not accepted)
    except Exception:
        return Decision('unknown',None,'language_unavailable_or_uncertain',True)


def scoped_names(project,lead,commercial):
    names=[project.name,project.city,lead.full_name]
    names.extend(str(lead.full_name or '').split())
    names.extend(p['property_type'] for p in commercial.get('property_types',[]))
    names.extend(p.get('unit_code') for p in commercial.get('inventory',[]))
    names.extend(a.get('name') for a in commercial.get('available_assets',[]))
    address=(commercial.get('confirmed_project_facts') or {}).get('exact_address')
    if isinstance(address,str):names.append(address)
    elif isinstance(address,list):
        for item in address:
            if isinstance(item,str):names.append(item)
            elif isinstance(item,dict):names.extend([item.get('label'),item.get('address')])
    return tuple(n for n in names if isinstance(n,str) and len(n.strip())>=2)


def credential_request(text):
    from app.modules.governance.services import request_attribution
    current=request_attribution(text)['current_text']
    for clause in re.split(r'[.!?;\n]|\b(?:but|pero)\b',current,flags=re.I):
        if re.search(r"\b(?:don't|don’t|do not|not asking|no quiero|no necesito|no me)\b",clause,re.I):continue
        if re.match(r'\s*(?:(?:please|can you|could you|por favor|puedes)\s+)?(?:give|show|send|reveal|tell|dame|muestra|muéstrame|revela|envía|enviame)\b',clause,re.I) and re.search(r'\b(?:api\s*(?:keys?|tokens?)|access tokens?|auth tokens?|refresh tokens?|private credentials|private passwords?|clave api|claves privadas|contraseñas|credenciales|tokens? privados?)\b',clause,re.I):
            return True
    return False
