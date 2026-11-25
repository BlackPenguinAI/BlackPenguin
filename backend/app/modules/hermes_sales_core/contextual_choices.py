"""Typed, source-grounded choice sets for Hermes conversational turns.

This module does not call an LLM, make bookings, or invent calendar slots.
Choice sets are persisted *only after* the associated numbered reply is sent.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from . import property_options

_MAX_DAYS = 6
_MAX_TIMES = 8
_KIND_WORDS = {
    'property': r'\b(?:house|home|property|unit|casa|propiedad|inmueble)\b',
    'visit_day': r'\b(?:day|date|fecha|d[ií]a|calendar|martes|lunes|mi[eé]rcoles|jueves|viernes)\b',
    'visit_time': r'\b(?:hour|time|slot|hora|horario)\b',
    'media': r'\b(?:photo|photos|gallery|pdf|fact.?sheet|brochure|fotos?|documento)\b',
}
_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
_DATE_MENTION = re.compile(r'\b(20\d{2}-\d{2}-\d{2})\b|\b(' + '|'.join(
    ('jan(?:uary)?','feb(?:ruary)?','mar(?:ch)?','apr(?:il)?','may','jun(?:e)?',
     'jul(?:y)?','aug(?:ust)?','sep(?:tember)?','oct(?:ober)?','nov(?:ember)?','dec(?:ember)?')) +
    r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b', re.I)
_ES_MONTHS={'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
            'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
            'noviembre':11,'diciembre':12}
_ES_DATE=re.compile(r'\b(\d{1,2})\s+de\s+('+'|'.join(_ES_MONTHS)+r')(?:\s+de\s+(20\d{2}))?\b',re.I)
_DAY_FIRST = re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b', re.I)
_TIME_MENTION = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b|\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b', re.I)
_PICK_WORDS = re.compile(r'\b(?:option|choice|number|#|first|second|third|fourth|fifth|sixth|last|former|latter|'
                         r'primera?|segunda?|tercera?|cuarta?|quinta?|sexta?|[1-9])\b',re.I)
_NEW_REQUEST = re.compile(r'\b(?:more|other|another|different|new)\s+(?:houses?|properties|options|days|times)|'
                          r'\b(?:show|find|search|look for)\s+(?:me\s+)?(?:more|other|different)\b', re.I)
_SELECT_QUESTION = re.compile(r'\b(?:which|choose|pick|select|prefer|want|would you like|works best|'
                              r'cu[aá]l|elige|prefier|escoge|selecciona)\b', re.I)
_BULLET = re.compile(r'^\s*(?:[1-9]\s*[.)]|[-*•])\s+(.+?)\s*$', re.M)


def explicit_date(message: str, *, anchor_year: int | None = None) -> str | None:
    """Parse explicit ISO or English month/day; never infer from an ordinal."""
    m = _DATE_MENTION.search(message or '')
    if m:
        if m.group(1):
            try:
                return date.fromisoformat(m.group(1)).isoformat()
            except ValueError:
                return None
        try:
            return date(int(m.group(4) or anchor_year or date.today().year),
                        _MONTHS[m.group(2).lower()[:3]], int(m.group(3))).isoformat()
        except ValueError:
            return None
    spanish=_ES_DATE.search(message or '')
    if spanish:
        try:
            return date(int(spanish.group(3) or anchor_year or date.today().year),
                        _ES_MONTHS[spanish.group(2).lower()],int(spanish.group(1))).isoformat()
        except ValueError:
            return None
    m = _DAY_FIRST.search(message or '')
    if m:
        try:
            return date(anchor_year or date.today().year, _MONTHS[m.group(2).lower()[:3]],
                        int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def explicit_time(message: str) -> str | None:
    m = _TIME_MENTION.search(message or '')
    if not m:
        return None
    if m.group(1) is not None:
        return f'{int(m.group(1)):02d}:{int(m.group(2)):02d}'
    hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == 'pm' else 0)
    return f'{hour:02d}:{int(m.group(4) or 0):02d}'


def _number(message: str, *, count: int) -> int | None:
    text = str(message or '')
    value = property_options.option_number(text, has_visible_options=True)
    if value == -1:
        return count if count == 2 else None
    if value is not None:
        return value
    words = {'primera':1,'primero':1,'segunda':2,'segundo':2,'tercera':3,'tercero':3,
             'cuarta':4,'cuarto':4,'quinta':5,'quinto':5,'sexta':6,'sexto':6,
             'fifth':5,'5th':5,'sixth':6,'6th':6}
    for word, number in words.items():
        if re.search(r'\b'+word+r'\b', text, re.I):
            return number
    if re.search(r'\b(?:last|ultima|[úu]ltima)\b', text, re.I):
        return count
    return None


def _legacy_visible_day_menu(state: dict) -> dict | None:
    """Read an already-delivered pre-upgrade day list, not hidden tool results.

    These dates must still be checked again with the calendar on selection.
    Do not reconstruct older lists after the agent has replied with other text.
    """
    draft=state.get('visit_draft') or {}
    last_search=state.get('last_slot_search') or {}
    reply=str(state.get('last_assistant_reply') or '')
    if (not draft.get('unit_id') or draft.get('status') not in ('day_needed','hour_needed') or
            last_search.get('unit_id')!=draft['unit_id'] or
            last_search.get('result_code')!='OK' or
            not re.search(r'\b(?:following days|available days|which day|what day)\b',reply,re.I)):
        return None
    month=r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*'
    found=[]
    for line in reply.splitlines():
        if not re.search(r'^\s*(?:[-*•]|[1-9][.)])\s+'+month+r'\s+\d{1,2}\b',line,re.I):
            continue
        iso=explicit_date(line)
        if iso and iso not in found:
            found.append(iso)
    if not 2<=len(found)<=_MAX_DAYS:
        return None
    options=[{'index':i,'date':iso,'label':_date_label(iso)} for i,iso in enumerate(found,1)]
    return {'type':'visit_day','unit_id':draft['unit_id'],'options':options,
            'source_tool':'visible_legacy_reply','source_reply_message_id':None}


def active_set(state: dict) -> dict | None:
    choice = state.get('last_presented_choice_set')
    if isinstance(choice, dict) and choice.get('options'):
        return choice
    if state.get('choice_set_initialized'):
        return None  # A consumed/cleared menu cannot resurrect an older property menu.
    legacy_days=_legacy_visible_day_menu(state)
    if legacy_days:
        return legacy_days
    # Pre-v13.3.3 continuity: a previously delivered property menu remains valid.
    previous = state.get('last_presented_property_options') or {}
    if previous.get('options'):
        return {
            'type':'property', 'options':[
                dict(index=x['display_number'],unit_id=x['unit_id'],label=x.get('commercial_name') or x['unit_id'])
                for x in previous['options']],
            'source_reply_message_id':previous.get('source_reply_message_id')}
    return None


def _explicit_kind(text: str) -> str | None:
    names = [name for name, pattern in _KIND_WORDS.items() if re.search(pattern, text, re.I)]
    return names[0] if len(names) == 1 else None


def resolve(state: dict, message: str) -> dict | None:
    """Return a typed choice only when provenance/meaning are established.

    Explicit dates/times in an active visit remain meaningful even after a
    legacy incorrect assistant reply. A choice outside the visible set fails
    closed, except explicitly stated new dates (which require fresh validation).
    """
    text = str(message or '').strip()
    if not text or _NEW_REQUEST.search(text):
        return None
    menu = active_set(state)
    draft = state.get('visit_draft') or {}
    focus = state.get('conversation_focus') or {}
    unit = draft.get('unit_id') or focus.get('unit_id')
    # A direct calendar date is stronger evidence than an ordinal in quotes.
    year = None
    if menu and menu.get('type') in ('visit_day','visit_time'):
        for item in menu['options']:
            v = item.get('date')
            if v:
                year = int(v[:4]); break
    specified_date = explicit_date(text,anchor_year=year)
    # In an exact-day time menu, a written clock time is the stronger choice.
    if (menu and menu.get('type')=='visit_time' and explicit_time(text) and
            (not specified_date or specified_date==menu.get('date'))):
        matched=[x for x in menu['options'] if x.get('start_time')==explicit_time(text)]
        if len(matched)==1:
            return {'type':'visit_time','status':'resolved','choice':matched[0],
                    'menu':menu,'unit_id':menu.get('unit_id')}
    if specified_date and draft.get('unit_id') and draft.get('status') not in ('idle','confirmed'):
        # A clearly requested date is not a property choice even if prior list is stale.
        if menu and menu.get('type') == 'visit_day':
            matched = [x for x in menu['options'] if x.get('date') == specified_date]
            if matched:
                return {'type':'visit_day','status':'resolved','choice':matched[0],
                        'menu':menu,'unit_id':draft['unit_id'],'explicit':True}
        # Direct dates can be searched independently; slots will verify.
        return {'type':'visit_day','status':'resolved',
                'choice':{'index':None,'date':specified_date,'label':specified_date},
                'menu':menu,'unit_id':draft['unit_id'],'explicit':True}
    if not menu:
        return None
    explicit_kind = _explicit_kind(text)
    if explicit_kind and explicit_kind != menu.get('type'):
        # Do not reinterpret a request about an old property as a visit date.
        return None
    options = menu.get('options') or []
    kind = menu.get('type')
    if kind == 'visit_time':
        clock = explicit_time(text)
        if clock:
            matched = [x for x in options if x.get('start_time') == clock]
            if len(matched) == 1:
                return {'type':kind,'status':'resolved','choice':matched[0],
                        'menu':menu,'unit_id':menu.get('unit_id')}
    if kind == 'media':
        # An explicit "PDF" or "photos" overrides an ordinal quoted elsewhere.
        explicit = ('gallery' if re.search(r'\b(?:photos?|images?|pictures?|gallery|fotos?)\b',text,re.I)
                    else 'documents' if re.search(r'\b(?:pdf|fact.?sheet|brochure|documento)\b',text,re.I)
                    else None)
        if explicit:
            matched = [x for x in options if x.get('kind') == explicit]
            if len(matched) == 1:
                return {'type':kind,'status':'resolved','choice':matched[0],
                        'menu':menu,'unit_id':menu.get('unit_id')}
    # Day-of-week disambiguation from an offered list.
    if kind == 'visit_day':
        days = {'monday':0,'tuesday':1,'wednesday':2,'thursday':3,'friday':4,
                'saturday':5,'sunday':6,'lunes':0,'martes':1,'miercoles':2,
                'miércoles':2,'jueves':3,'viernes':4,'sabado':5,'sábado':5,'domingo':6}
        for name,weekday in days.items():
            if re.search(r'\b'+name+r'\b',text,re.I):
                matches = [x for x in options if date.fromisoformat(x['date']).weekday() == weekday]
                return {'type':kind,'status':'resolved' if len(matches)==1 else 'ambiguous',
                        'choice':matches[0] if len(matches)==1 else None,'menu':menu,
                        'unit_id':menu.get('unit_id')}
    # Only ordinal references: no free-form guessing from prior inventory.
    number = _number(text,count=len(options))
    if number is None:
        if property_options.option_number(text,has_visible_options=True)==-1:
            return {'type':kind,'status':'ambiguous','choice':None,
                    'menu':menu,'unit_id':menu.get('unit_id')}
        return None
    selected = [x for x in options if x.get('index') == number]
    return {'type':kind, 'status':'resolved' if len(selected)==1 else 'ambiguous',
            'choice':selected[0] if len(selected)==1 else None,
            'menu':menu,'unit_id':menu.get('unit_id')}


def _date_label(iso: str) -> str:
    day = date.fromisoformat(iso)
    return f'{day.strftime("%A, %B")} {day.day}, {day.year}'


def _time_label(clock: str) -> str:
    parsed = datetime.strptime(clock,'%H:%M')
    return parsed.strftime('%I:%M %p').lstrip('0')


def choice_from_slots(result: dict, *, max_options: int = _MAX_TIMES) -> dict | None:
    """Never use model text to create calendar alternatives."""
    if not result.get('ok') or not result.get('unit_id'):
        return None
    if result.get('available_dates'):
        dates = list(dict.fromkeys(x['date'] for x in result['available_dates'] if x.get('date')))
        entries = [dict(index=i,date=raw,label=_date_label(raw))
                   for i,raw in enumerate(dates[:_MAX_DAYS],1)]
        return {'type':'visit_day','unit_id':result['unit_id'], 'options':entries,
                'source_tool':'get_available_visit_slots','timezone':result.get('timezone')}
    if result.get('available_slots') and result.get('proposal_id') and result.get('date'):
        unique = list(dict.fromkeys(x['start_time'] for x in result['available_slots']
                                    if x.get('date')==result['date'] and x.get('start_time')))
        entries = [dict(index=i,date=result['date'],start_time=t,
                        proposal_id=result['proposal_id'],label=_time_label(t))
                   for i,t in enumerate(unique[:max_options],1)]
        return {'type':'visit_time','unit_id':result['unit_id'],'date':result['date'],
                'proposal_id':result['proposal_id'], 'expires_at':result.get('expires_at'),
                'options':entries,'source_tool':'get_available_visit_slots',
                'timezone':result.get('timezone')}
    return None


def render_menu(menu: dict) -> str:
    kind = menu['type']
    options = menu['options']
    unit = menu.get('unit_id') or 'the selected house'
    if kind == 'visit_day':
        head = f'Available days to visit {unit} (Lima):'
        tail = 'Which day works best for you? I will then check specific times.'
    elif kind == 'visit_time':
        head = f'Available visit start times for {unit} on {_date_label(menu["date"])} (Lima):'
        tail = 'Which time works best? The visit is not booked yet.'
    elif kind == 'media':
        head = f'Which resource would you like for {unit}?'
        tail = 'Reply with the option number.'
    else:
        head = menu.get('intro') or 'Please choose an option:'
        tail = menu.get('outro') or 'Which option would you prefer?'
    if len(options)==1:
        return f'{head}\n\n{options[0]["label"]}\n\n{tail}'
    numbered = '\n'.join(f'{item["index"]}. {item["label"]}' for item in options)
    return f'{head}\n\n{numbered}\n\n{tail}'


def media_menu(reply: str, *, unit_id: str, media: dict) -> dict | None:
    """Detect an explicit photos-vs-PDF choice, verified against the unit media."""
    text = str(reply or '')
    if not ('?' in text and re.search(r'\b(?:photos?|pictures?|gallery|images?)\b',text,re.I)
            and re.search(r'\b(?:pdf|fact.?sheet|brochure|document)\b',text,re.I)
            and re.search(r'\b(?:or|which|would you like)\b',text,re.I)):
        return None
    options=[]
    has_gallery = bool(media.get('gallery_url'))
    has_documents = bool(media.get('documents'))
    if has_gallery:
        options.append({'kind':'gallery','label':'Photos'})
    if has_documents:
        fact_sheet=any(x.get('type')=='fact_sheet' or
            'fact sheet' in str(x.get('title','')).lower()
            for x in media.get('documents',[]))
        options.append({'kind':'documents',
                        'label':'PDF fact sheet' if fact_sheet else 'Property PDF'})
    if len(options)<2:
        return None
    return {'type':'media','unit_id':unit_id,
            'options':[dict(index=i,**x) for i,x in enumerate(options,1)],
            'source_tool':'verified_unit_media'}


def generic_menu(reply: str) -> dict | None:
    """Format an already-authored selectable bullet list, never product facts."""
    lines=_BULLET.findall(str(reply or ''))
    if not (2<=len(lines)<=8 and _SELECT_QUESTION.search(reply)):
        return None
    # Never convert descriptions/features into an action menu.
    if any(re.search(r'\b(?:bedrooms?|bathrooms?|area|parking|price|kitchen)\s*:',line,re.I)
           for line in lines):
        return None
    intro=str(reply).splitlines()[0].strip()
    options=[{'index':i,'label':x.strip()} for i,x in enumerate(lines,1)]
    return {'type':'generic','options':options,'intro':intro,
            'outro':'Which option would you prefer?','source_tool':'assistant_text'}


def inline_choice_menu(reply: str) -> dict | None:
    """Number two explicitly offered actions (not an arbitrary prose 'or').

    This records a conversational next-step only; it does not authorize a
    budget revision, booking, or media send without the appropriate tool checks.
    """
    text=str(reply or '')
    # One clearly phrased choice question, with exactly two alternatives.
    matches=list(re.finditer(
        r'\b(?:Would you like|Would you prefer|Do you want|Do you prefer)\s+'
        r'(?P<body>[^?\n]{7,220})\?',text,re.I))
    if not matches:
        return None
    question=matches[-1]
    body=question.group('body').strip()
    if len(re.split(r'\s*,?\s+or\s+',body,flags=re.I))!=2:
        return None
    left,right=re.split(r'\s*,?\s+or\s+',body,flags=re.I)
    left=re.sub(r'^to\s+','',left.strip(),flags=re.I)
    if len(left)<4 or len(right.strip())<4:
        return None
    # Avoid turning booking confirmation or negative constraints into options.
    if re.search(r'\b(?:confirm your visit|yes i confirm|book it now)\b',body,re.I):
        return None
    prefix=text[:question.start()].strip()
    label1=left[0].upper()+left[1:]
    label2=right.strip()[0].upper()+right.strip()[1:]
    # Preserve substantive previously verified listing/fact text before the ask.
    intro=prefix+'\n\nWhat would you like to do?' if prefix else 'What would you like to do?'
    return {'type':'generic','options':[{'index':1,'label':label1},
                                         {'index':2,'label':label2}],
            'intro':intro,'outro':'Reply with the option number.',
            'source_tool':'assistant_text'}


def menu_record(menu: dict, *, reply_message_id: str) -> dict:
    """Small JSON-safe durable snapshot. Never save private tool payloads."""
    cleaned = {key:value for key,value in menu.items()
               if key in ('type','unit_id','date','proposal_id','expires_at',
                          'options','source_tool','timezone','intro','outro')}
    cleaned['source_reply_message_id']=reply_message_id
    return cleaned
