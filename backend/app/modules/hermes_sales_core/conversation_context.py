"""Conservative reference/topic resolution, extracted from Hermes v13.3.3.

P01 preserves the demo's H-### code conventions. P02 must map them to
approved BlackPenguin project/property/unit UUIDs and mixed typologies.
This module never grants consent to book or alters commercial criteria.
"""
from __future__ import annotations
import re
from typing import Any

_CODE = re.compile(r'(?<![A-Z0-9])H-\d{3}(?![A-Z0-9])', re.I)
_ORDINALS = (
    (0, r'\b(?:first(?: one| house| option)?|1st|option 1|#1)\b'),
    (1, r'\b(?:second(?: one| house| option)?|2nd|option 2|#2)\b'),
    (2, r'\b(?:third(?: one| house| option)?|3rd|option 3|#3)\b'),
    (3, r'\b(?:fourth(?: one| house| option)?|4th|option 4|#4)\b'),
)
_COMPARATIVE = (
    (r'\b(?:cheapest|least expensive|lowest priced|lowest price)\b', 'price_usd', 'min'),
    (r'\b(?:most expensive|highest priced|highest price)\b', 'price_usd', 'max'),
    (r'\b(?:largest|biggest|most spacious|greatest area)\b', 'area_sqm', 'max'),
    (r'\b(?:smallest|least spacious|smallest area)\b', 'area_sqm', 'min'),
)


def mentioned_codes(text: str, units: dict[str, dict]) -> list[str]:
    return list(dict.fromkeys(code.upper() for code in _CODE.findall(text or '')
                              if code.upper() in units))


def presented_units(reply: str, units: dict[str, dict]) -> list[str]:
    return mentioned_codes(reply, units)[:10]


def resolved_reference(state: dict, text: str, units: dict[str, dict]) -> dict[str, Any]:
    named = mentioned_codes(text, units)
    if len(named) == 1:
        return {'unit_id': named[0], 'reason': 'explicit_unit', 'ambiguous': False}
    if len(named) > 1:
        return {'unit_id': None, 'reason': 'multiple_explicit_units', 'ambiguous': True, 'candidates': named}
    recent = [c for c in (state.get('last_presented_units') or []) if c in units]
    shortlist = [c for c in (state.get('shortlisted_unit_ids') or []) if c in units]
    options = recent or shortlist
    for index, pattern in _ORDINALS:
        if re.search(pattern, text, re.I):
            if index < len(options):
                return {'unit_id': options[index], 'reason': 'ordinal', 'ambiguous': False}
            return {'unit_id': None, 'reason': 'unknown_ordinal', 'ambiguous': True, 'candidates': options}
    for pattern, field, method in _COMPARATIVE:
        if re.search(pattern, text, re.I) and len(options) > 1:
            numbers = [(units[code].get(field), code) for code in options]
            if all(isinstance(n, (int, float)) for n, _ in numbers):
                extreme = (min if method == 'min' else max)(n for n, _ in numbers)
                matches = [code for number, code in numbers if number == extreme]
                if len(matches) == 1:
                    return {'unit_id': matches[0], 'reason': 'comparative', 'ambiguous': False}
                return {'unit_id': None, 'reason': 'comparative_tie', 'ambiguous': True, 'candidates': matches}
    if len(recent) > 1:
        return {'unit_id': None, 'reason': 'multiple_recent_options', 'ambiguous': True, 'candidates': recent}
    if len(recent) == 1:
        return {'unit_id': recent[0], 'reason': 'single_recent_option', 'ambiguous': False}
    focus = (state.get('conversation_focus') or {}).get('unit_id') or state.get('exploring_unit_id')
    if focus in units and not (state.get('conversation_focus') or {}).get('ambiguous'):
        return {'unit_id': focus, 'reason': 'existing_focus', 'ambiguous': False}
    if len(shortlist) == 1:
        return {'unit_id': shortlist[0], 'reason': 'single_matching_option', 'ambiguous': False}
    return {'unit_id': None, 'reason': 'unresolved', 'ambiguous': len(shortlist) > 1,
            'candidates': shortlist[:5]}


def topic(text: str) -> str | None:
    text = (text or '').lower()
    subjects = [
        ('area', r'\b(?:area|size|square footage|sq\.?\s*ft|square feet|square meters?|square metres?|m2|m²|spacious|large)\b'),
        ('price', r'\b(?:price|cost|how much|cheaper|expensive|budget)\b'),
        ('bedrooms', r'\b(?:bedrooms?|beds?)\b'),
        ('bathrooms', r'\b(?:bathrooms?|baths?)\b'),
        ('kitchen', r'\b(?:kitchen|open[- ]plan)\b'),
        ('backyard', r'\b(?:backyard|garden|yard|outdoor)\b'),
        ('parking', r'\b(?:parking|garage|car space)\b'),
        ('location', r'\b(?:where|located|location|address|map|maps|directions|district)\b'),
        ('gallery', r'\b(?:photos?|gallery|pictures?|images?)\b'),
        ('documents', r'\b(?:pdf|documents?|brochures?|fact.?sheets?|floor.?plans?|blueprints?)\b'),
        ('availability', r'\b(?:available|ready|move in|delivery)\b'),
    ]
    for key, pattern in subjects:
        if re.search(pattern, text, re.I):
            return key
    return None


def is_detail_question(text: str) -> bool:
    return bool(topic(text) in {'area','price','bedrooms','bathrooms','kitchen','backyard',
                               'parking','location','gallery','documents','availability'}) and not bool(re.search(
        r'\b(?:book|schedule|confirm|reschedule|cancel|appointment|visit\s+on)\b', text or '', re.I))


def is_property_confirmation(text: str, last_reply: str) -> bool:
    if not re.fullmatch(r'\s*(?:yes|yes please|sure|i am interested|'
                        r'yes,? i am interested(?: in (?:that|this) property)?)'
                        r'[.!]?\s*', text or '', re.I):
        return False
    return bool(re.search(r'\b(?:explore|details|learn more|tell you more|continue exploring)\b',
                          last_reply or '', re.I)) and not bool(re.search(
        r'\b(?:reserve|book|appointment|confirm your visit)\b', last_reply or '', re.I))
