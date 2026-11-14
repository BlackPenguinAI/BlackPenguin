"""Explicit bedroom discovery, grounded in the current approved catalog.

A need is not a property reference or booking consent. Deliberately bounded to
literal own requests; quoted, hypothetical, negative and ranged needs are not
silently converted into an exact bedroom constraint.
"""
import re
from .understanding_contract import Understanding

VERSION = 'sales-needs-search/1.2'
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


def literal_statement(text):
    need=criterion(text)
    return bool(need and re.fullmatch(r"\s*(?:Actually[, ]+)?"+re.escape(need['evidence'])+r"[.!?]?\s*",text,re.I))


def literal_read(value,text):
    """Read-only authorization from a complete literal command, not model confidence.

    Never extends to effects, ambiguous/ranged/mixed requests or rejected inference.
    Caller must already have an accepted interpretation and enforce saved holds.
    """
    return bool(literal_statement(text) and len(value.requests)==1 and value.permits('catalog')
        and value.requests[0].reference_id is None and not value.references and not value.comparison
        and not value.alternatives and not value.constraints and not value.releases
        and not any(getattr(value,k) for k in ('visit','reschedule','cancellation','wait','moderation','appointment_query','selected_reference_id','personal_facts','preference_withdrawals','source_purposes','objections','empathy','courtesy'))
        and all(p.key=='bedrooms' for p in value.preferences)
        and search(value,[],{'exhaustive':False}) is not None)


def normalize(value, text, commercial):
    need = criterion(text)
    if not need or (value.comparison and not literal_statement(text)) or value.alternatives or value.constraints:
        return value, []
    # A named home or a pronoun keeps its own explicit reference semantics.
    if any(re.search(r'(?<!\w)'+re.escape(p['property_type'])+r'(?!\w)', text, re.I)
           for p in commercial.get('property_types', []) if p.get('property_type')):
        return value, []
    data = value.model_dump(mode='json')
    comparison_removed=bool(data['comparison'] and literal_statement(text))
    if comparison_removed:data['comparison']=None
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
    return result, [{'field':'requests', 'action':'literal_bedroom_need_is_catalog_search', 'removed_unrequested_comparison':comparison_removed, 'model_confidence_preserved':value.confidence, **need}]


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
            'unknown_bedrooms':len(unknown), 'unknown_property_ids':[p['id'] for p in unknown], 'exhaustive':coverage.get('exhaustive') is True,
            'matching_property_ids':[p['id'] for p in matching]}


def answer(result):
    n = result['bedrooms']
    if result.get('exploring_unknown'):
        options=result['unknown_options']
        if not options:return 'Those homes are no longer listed among the options I can show you.'
        blocks=['Here are the homes you asked to explore:']
        for row in options:
            details=[]
            if row.get('bedrooms') is None:details.append('bedroom details are not available')
            else:details.append(f"{row['bedrooms']:g} bedroom"+('s' if row['bedrooms']!=1 else ''))
            if row.get('starting_price') is not None and row.get('currency'):details.append(f"from {row['starting_price']:,.2f} {row['currency']}")
            blocks.append(row['property_type']+' — '+', '.join(details)+'.')
            if row.get('available_units')==0:blocks.append('This home is listed as unavailable.')
            elif row.get('available_units') is None or not row.get('inventory_updated_at'):blocks.append('Availability for this home still needs confirmation.')
        return '\n\n'.join(blocks)
    rows = result['matches']
    if rows:
        blocks = [f"Here {'is a' if len(rows)==1 else 'are the'} {n}-bedroom {'option' if len(rows)==1 else 'options'} in this project:"]
        for row in rows:
            details = [f"{n} bedroom"+("s" if n!=1 else "")]
            if row.get('area_min') is not None:
                low, high = row['area_min'], row.get('area_max')
                details.append(f'{low:g}'+(f'–{high:g}' if high is not None and high != low else '')+' '+str(row.get('area_unit') or '(area unit unconfirmed)'))
            if row.get('starting_price') is not None and row.get('currency'):
                details.append(f"from {row['starting_price']:,.2f} {row['currency']}")
            blocks.append(row['property_type']+' — '+', '.join(details)+'.')
            if row.get('available_units') is None or not row.get('inventory_updated_at'):
                blocks.append('Current availability for '+row['property_type']+' still needs confirmation.')
        return '\n\n'.join(blocks)
    if result['sold_out']:
        base = f'The {n}-bedroom homes I have details for are listed as unavailable.'
    elif result['unknown_bedrooms']:
        return f"I don't have bedroom details for some homes, so I can't confirm a {n}-bedroom option in this project."
    else:
        base = f"I don't have a {n}-bedroom option to show you in this project."
    if result['unknown_bedrooms']:
        base += " I don't have bedroom details for some other homes in this project."
    return base


def closing(result):
    if result.get('exploring_unknown'):return 'Which home would you like to know more about?' if result['unknown_options'] else 'Would you like to explore the other homes in this project?'
    if len(result['matches']) == 1:
        return 'Would you like to know more about '+result['matches'][0]['property_type']+'?'
    if result['matches']:
        return 'Which of these options would you like to explore?'
    if result['unknown_bedrooms']:return 'Would you like to see those homes?'
    return f'Are {result["bedrooms"]} bedrooms essential, or would you consider another bedroom count?'


def accepts_unknown_offer(text):
    return bool(re.fullmatch(r"\s*(?:yes(?:[, ]+(?:please|show me(?: those (?:other )?homes)?))?|please show me those homes|show me those homes)[.!]?\s*",text,re.I))


def unknown_options(db,scope,text,types):
    """Read only the latest accepted, complete offer in this conversation.

    IDs are revalidated against the current approved catalog. Acceptance permits
    listing, never selecting a property or performing another action.
    """
    from .turn_context import latest_outbound
    from .reference_resolution import accepted
    from .conversation_scope import scoped_messages_query
    message=latest_outbound(db,scope.conversation_id)
    if not message or not accepted(message) or not accepts_unknown_offer(text):return None
    meta=message.metadata_json or {};offer=meta.get('needs_unknown_offer')
    if not offer or not offer.get('property_ids'):return None
    group=meta.get('delivery_group') or {}
    if group.get('total',1)>1:
        from .dialogue_store import check_scope
        conversation=check_scope(db,scope)
        parts=scoped_messages_query(db,conversation).filter_by(direction='outbound').all()
        indexes={((p.metadata_json or {}).get('delivery_group') or {}).get('part') for p in parts if (p.metadata_json or {}).get('delivery_group',{}).get('key')==group.get('key') and accepted(p)}
        if indexes!=set(range(1,group['total']+1)):return None
    rows=[p for p in types if p['id'] in set(offer['property_ids'])]
    return {'version':VERSION,'bedrooms':offer['bedrooms'],'matches':[],'sold_out':[],
        'unknown_bedrooms':sum(p.get('bedrooms') is None for p in rows),'unknown_property_ids':[],
        'exhaustive':False,'matching_property_ids':[],'exploring_unknown':True,'unknown_options':rows}
