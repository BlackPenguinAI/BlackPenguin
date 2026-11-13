"""Explicit bedroom discovery, grounded in the current approved catalog.

A need is not a property reference or booking consent. Deliberately bounded to
literal own requests; quoted, hypothetical, negative and ranged needs are not
silently converted into an exact bedroom constraint.
"""
import re
from .understanding_contract import Understanding

VERSION = 'sales-needs-search/1.0'
WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}
NEED = re.compile(r"\b(?:I(?: am|'m|’m|m)? (?:looking for|want|need|prefer)|(?:please )?(?:show|find)(?: me)?|do you have|are there)\s+(?:(?:a|an|any)\s+)?(?P<count>[1-6]|one|two|three|four|five|six)[ -]?(?:bedrooms?|beds?|br)\b(?:\s+(?:homes?|houses?|apartments?|properties))?", re.I)
UNSAFE = re.compile(r"\b(?:not|don't|don’t|do not|never|friend|said|says|told|if|suppose|at least|at most|minimum|maximum|or more|or fewer|between)\b|[\"“”]", re.I)


def criterion(text):
    from app.modules.governance.services import request_attribution
    own = request_attribution(text)['current_text']
    if UNSAFE.search(own):
        return None
    matches = list(NEED.finditer(own))
    counts = re.findall(r'\b([1-6]|one|two|three|four|five|six)[ -]?(?:bedrooms?|beds?|br)\b', own, re.I)
    if len(matches) != 1 or len(counts) != 1:
        return None
    token = matches[0]['count'].lower()
    return {'bedrooms': WORDS[token] if token in WORDS else int(token), 'evidence': matches[0].group()}


def normalize(value, text, commercial):
    need = criterion(text)
    if not need or value.comparison or value.alternatives or value.constraints:
        return value, []
    # A named home or a pronoun keeps its own explicit reference semantics.
    if any(re.search(r'(?<!\w)'+re.escape(p['property_type'])+r'(?!\w)', text, re.I)
           for p in commercial.get('property_types', []) if p.get('property_type')):
        return value, []
    data = value.model_dump(mode='json')
    affected = [r for r in data['requests'] if r['polarity'] == 'request' and r['topic'] in {'catalog', 'inventory', 'property_details', 'other'} and (need['evidence'].lower() in r['evidence'].lower() or r['evidence'].lower() in need['evidence'].lower())]
    if not affected:
        # This narrow literal statement is itself an information request.
        if data['requests'] or data['visit'] :
            return value, []
        key = 'needs_catalog'
        data['requests'] = [dict(id=key, topic='catalog', subject=None, polarity='request', evidence=need['evidence'], reference_id=None)]
        data['all_of'] = [key]
    else:
        for row in affected:
            row.update(topic='catalog', reference_id=None, detail_fields=[], feature=None)
    if affected and len(affected)==len(data['requests']) and not data['visit']:
        data['requires_clarification']=False
        data['clarification_question']=None
    used = {r['reference_id'] for r in data['requests'] if r.get('reference_id')}
    if not data['visit'] and not used:
        data['selected_reference_id'] = None
        data['references'] = []
    # Preserve independent actions and references, but never select a property
    # merely because its bedroom count matches the need.
    data['preferences'] = [p for p in data['preferences'] if p['key'] != 'bedrooms'] + [dict(key='bedrooms', value=str(need['bedrooms']), evidence=need['evidence'], status='declared')]
    result = Understanding.model_validate(data).check_evidence(text)
    return result, [{'field':'requests', 'action':'literal_bedroom_need_is_catalog_search', **need}]


def search(understanding, types, coverage):
    if not understanding or not understanding.permits('catalog'):
        return None
    prefs = [p for p in understanding.preferences if p.key == 'bedrooms' and p.status == 'declared']
    if len(prefs) != 1:
        return None
    need = criterion(prefs[0].evidence)
    if not need or str(need['bedrooms']) != prefs[0].value:
        return None
    number = need['bedrooms']
    matching = [p for p in types if p.get('bedrooms') == number and p.get('available_units') != 0]
    sold = [p for p in types if p.get('bedrooms') == number and p.get('available_units') == 0]
    unknown = [p for p in types if p.get('bedrooms') is None]
    return {'version':VERSION, 'bedrooms':number, 'matches':matching, 'sold_out':sold,
            'unknown_bedrooms':len(unknown), 'exhaustive':coverage.get('exhaustive') is True,
            'matching_property_ids':[p['id'] for p in matching]}


def answer(result):
    n = result['bedrooms']
    rows = result['matches']
    if rows:
        blocks = [f"Here {'is a' if len(rows)==1 else 'are the'} {n}-bedroom {'option' if len(rows)==1 else 'options'} in this project:"]
        for row in rows:
            details = [f"{n} bedrooms"]
            if row.get('area_min') is not None:
                low, high = row['area_min'], row.get('area_max')
                details.append(f'{low:g}'+(f'–{high:g}' if high is not None and high != low else '')+' '+str(row.get('area_unit') or '(area unit unconfirmed)'))
            if row.get('starting_price') is not None and row.get('currency'):
                details.append(f"from {row['starting_price']:,.2f} {row['currency']}")
            blocks.append(row['property_type']+' — '+', '.join(details)+'.')
            if row.get('available_units') is None or not row.get('inventory_updated_at'):
                blocks.append('Current availability for '+row['property_type']+' still needs confirmation.')
        if result['unknown_bedrooms'] or not result['exhaustive']:
            blocks.append('The remaining catalog information is incomplete, so these may not be all the matching options.')
        return '\n\n'.join(blocks)
    if result['sold_out']:
        base = f'The {n}-bedroom options listed here have a last confirmed quantity of zero.'
    else:
        base = f'I do not have a confirmed {n}-bedroom option to show you in this project.'
    if result['unknown_bedrooms'] or not result['exhaustive']:
        base += ' Some catalog or bedroom details are missing, so I cannot rule out other matching options.'
    return base


def closing(result):
    if len(result['matches']) == 1:
        return 'Would you like to know more about '+result['matches'][0]['property_type']+'?'
    if result['matches']:
        return 'Which of these options would you like to explore?'
    return f'Are {result["bedrooms"]} bedrooms essential, or would you consider another bedroom count?'
