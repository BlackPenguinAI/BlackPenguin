"""HEI-02: scoped conversational continuity for the existing P04 draft lane.

No model calls, CRM writes or external effects here. Names and numbered choices
are resolved only against the current approved snapshot and delivered dialogue.
The port still inherits P04's simulation-only booking and authorization checks.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import re
from uuid import uuid4

from .bp_operational_port import BPOperationalDraftPort, CONFIRM_EXPIRY_MINUTES
from .choice_state import resolve_visible_choice, record_delivered_menu
from .bp_operation_receipts import visible_menu
from . import commercial_turn, sales_preferences

# Sentences about the current goal are guidance, not a second interpretation
# model or replacement system prompt. Published Staff policy remains pinned.
GUIDANCE = (
    'Use the current verified property focus for implicit references. Use commercial '
    'names in buyer-facing text; for visit menus and recaps also include the exact reference required by existing receipt checks. Keep a pending visit '
    'separate from property exploration. Never assume a comparison changes primary '
    'preferences. Do not ask for facts already present in the registered profile or '
    'dialogue. List selectable verified properties with consecutive numbers, one '
    'option per line, and their exact display_name. Follow resolved_visible_choice '
    'by its type (property, visit_day, visit_time, media), not an old shortlist. '
    'An ambiguous reference needs one targeted clarification. A draft media request '
    'or slot selection is not a delivered link or confirmed booking.'
)


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def display_name(row):
    # Unit codes distinguish multiple units of the same typology.
    name, ref = _text(row.get('property_type')), _text(row.get('reference'))
    if row.get('kind') == 'unit' and name and name.casefold() != ref.casefold():
        return f'{name} ({ref})'
    return (name or ref) if row.get('kind') == 'property_type' else ref


def _matches(text, label):
    return bool(label and re.search(r'(?<![\w-])' + re.escape(label) + r'(?![\w-])', text, re.I))


def named_rows(rows, text):
    """Find explicit names/codes, ignoring overlapping shorter aliases.

    A name shared by distinct units is not an exact unit selection. Type-level
    rows can still answer a named type without choosing an arbitrary unit.
    """
    hits = []
    for row in rows:
        labels = {_text(row.get('reference')), display_name(row)}
        if row.get('kind') == 'property_type':
            labels.add(_text(row.get('property_type')))
        # Generic category words are filters, not an exact property choice.
        generic = {'house','home','apartment','condo','property','unit','townhouse','villa','houses','apartments'}
        for label in labels - {''}:
            if label.casefold() in generic:
                continue
            for m in re.finditer(r'(?<![\w-])' + re.escape(label) + r'(?![\w-])', text, re.I):
                hits.append((m.start(), m.end(), row))
    result = {}
    for start, end, row in hits:
        if any(s <= start and e >= end and (s < start or e > end) for s, e, _ in hits):
            continue
        result[row['reference']] = row
    return list(result.values())


def set_focus(state, row, project_id):
    state['conversation_focus'] = {
        'project_id': project_id,
        'unit_id': row['reference'] if row['kind'] == 'unit' else None,
        'property_type_id': row['id'] if row['kind'] == 'property_type' else None,
        'ambiguous': False,
    }


def focus_ref(state):
    focus = state.get('conversation_focus') or {}
    return focus.get('unit_id') or focus.get('property_type_id')


_NUMBERED = re.compile(r'^\s*([1-9])\s*[.)]\s+(.+?)\s*$')
_INLINE = re.compile(r'(?<![\w.])([1-9])[.)]\s+')


def delivered_property_menu(reply, rows):
    """Bind the *displayed subset/order*, not the tool's search result order.

    Only one contiguous unambiguous numbered list, 2..9 items, is accepted.
    No hidden results, duplicate numbers or repeated/unknown property references.
    """
    lines = [m for line in reply.splitlines() if (m := _NUMBERED.fullmatch(line))]
    if not 2 <= len(lines) <= 9 or [int(m[1]) for m in lines] != list(range(1, len(lines)+1)):
        return None
    options = []
    seen = set()
    for m in lines:
        value = m[2].replace('**', '')
        matches = []
        for row in rows:
            label = display_name(row)
            ref = _text(row.get('reference'))
            # A line must begin with the exact label/code, not mention a second
            # property in prose. Require a real word/delimiter boundary.
            for candidate in dict.fromkeys((label, ref)):
                if candidate and re.match(re.escape(candidate) + r'(?=$|\s|[:;,\-–—])', value, re.I):
                    matches.append((len(candidate), row, candidate))
        if not matches:
            return None
        longest = max(x[0] for x in matches)
        best = [x for x in matches if x[0] == longest]
        if len({x[1]['reference'] for x in best}) != 1:
            return None
        _, row, label = best[0]
        other = {r['reference'] for r in named_rows(rows, value)} - {row['reference']}
        if other or row['reference'] in seen:
            return None
        seen.add(row['reference'])
        options.append({'index':int(m[1]), 'unit_id':row['reference'], 'label':label})
    return {'type':'property', 'source_tool':'search_properties', 'options':options}


def normalize_property_list(reply, rows):
    """Repair only an inline list whose every option is independently proven.

    Preserve all content and order. Never rewrite arbitrary numeric prose.
    """
    existing = delivered_property_menu(reply, rows)
    if existing:
        return reply, existing
    if not 2 <= len(rows) <= 20:
        return reply, None
    matches = list(_INLINE.finditer(reply))
    if not 2 <= len(matches) <= 9 or [int(m[1]) for m in matches] != list(range(1,len(matches)+1)):
        return reply, None
    pieces = [reply[:matches[0].start()].rstrip()]
    for i, m in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(reply)
        pieces.append(reply[m.start():end].strip())
    candidate = '\n'.join(p for p in pieces if p)
    menu = delivered_property_menu(candidate, rows)
    return (candidate, menu) if menu else (reply, None)


def _type_row(raw):
    if not isinstance(raw, dict) or not raw.get('id'):
        return None
    return {
        'id':raw['id'], 'reference':str(raw['id']), 'kind':'property_type',
        'property_type':raw.get('property_type'), 'bedrooms':raw.get('bedrooms'),
        'bathrooms':raw.get('bathrooms'), 'area':raw.get('area_min'),
        'price':raw.get('starting_price'), 'currency':raw.get('currency'),
        'status':'catalog_type', 'inventory_updated_at':raw.get('inventory_updated_at'),
        'available_units':raw.get('available_units'), 'description':raw.get('description'),
        'verified_features':{}, 'availability_verified':False,
    }



def scoped_dialogue(db, scope, conversation, inbound):
    """Read the current opportunity only, even when a phone thread was reused.

    Attribution is checked before limiting history. Internal resume envelopes,
    rejected outbound messages and undelivered drafts are not buyer dialogue.
    Return latest delivered assistant row as the menu/offer evidence boundary.
    """
    from app.modules.sales_agent.models import SalesConversationLeadContext, SalesMessage
    contexts = db.query(SalesConversationLeadContext).filter_by(conversation_id=scope.conversation_id).all()
    active = [c for c in contexts if c.lead_id == scope.lead_id and c.is_active]
    if contexts and len(active) != 1:
        raise PermissionError('Current opportunity is not uniquely active')
    activated = getattr(active[0], 'activated_at', None) if active else None
    if activated is not None and inbound.created_at < activated:
        raise PermissionError('Inbound precedes the active opportunity')
    query = db.query(SalesMessage).filter(
        SalesMessage.conversation_id == conversation.id,
        SalesMessage.channel == conversation.channel,
        SalesMessage.created_at <= inbound.created_at,
        SalesMessage.role.in_(['user','assistant']),
    )
    if activated is not None:
        query = query.filter(SalesMessage.created_at >= activated)
    # Explicitly attributed rows only for reused threads with no activation
    # timestamp. No inference from a phone number or the current Lead ID.
    messages = []
    latest = None
    for row in query.order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).yield_per(50):
        if row.id == inbound.id:
            continue
        if row.created_at == inbound.created_at and row.id > inbound.id:
            continue
        meta = row.metadata_json or {}
        if meta.get('lead_id', scope.lead_id) != scope.lead_id or meta.get('project_id', scope.project_id) != scope.project_id:
            continue
        if contexts and activated is None and (meta.get('lead_id') != scope.lead_id or meta.get('project_id') != scope.project_id):
            continue
        if meta.get('resume_context') or not isinstance(row.content, str) or not row.content.strip():
            continue
        if row.direction == 'outbound' and row.role == 'assistant' and row.status in {'sent','delivered','accepted','read'}:
            if latest is None:
                latest = row
            role = 'assistant'
        elif row.direction == 'inbound' and row.role == 'user' and row.status in {'received','processed'}:
            role = 'user'
        else:
            continue
        if len(messages) < 25:
            messages.append({'role':role, 'content':row.content[:4000]})
        if len(messages) >= 25 and latest is not None:
            break
    return list(reversed(messages[:25])), latest


def invalidate_stale_choice(state, latest):
    menu = state.get('last_presented_choice_set')
    if menu and (latest is None or menu.get('source_reply_message_id') != latest.id or not visible_menu(latest.content, menu)):
        state['last_presented_choice_set'] = None
        state['choice_set_initialized'] = True
        state['last_presented_units'] = []
    offered = (state.get('offered_assets') or {}).get('presented_offer')
    if offered and (latest is None or offered.get('source_reply_message_id') != latest.id):
        state['offered_assets'].pop('presented_offer', None)


_MEDIA_WORDS = {
    'floor_plan': r'\bfloor[ -]*plans?\b',
    'gallery_image': r'\b(?:photos?|pictures?|gallery|images?)\b',
    'brochure': r'\bbrochures?\b',
    'unit_sheet': r'\b(?:fact|unit)[ -]*sheets?\b',
}
_PDF = re.compile(r'\b(?:pdfs?|documents?)\b', re.I)
_YES = re.compile(r"\s*(?:yes(?:,?\s+please)?|sure|please do|send it|go ahead)\s*[.!]?\s*", re.I)
_OFFER = re.compile(r'\b(?:would you like|shall i|can i|may i|want me to|i can (?:send|share|show))\b', re.I)


def media_tags(text):
    return [tag for tag, pattern in _MEDIA_WORDS.items() if re.search(pattern, text, re.I)]


def asset_offer_from_reply(reply, row, verified):
    # Only a single concrete category from verified discovery may authorize
    # a later affirmative reference. This is context, never effect consent.
    if not _OFFER.search(reply) or re.search(r'\bor\b', reply, re.I) or reply.count('?') > 1:
        return None
    tags = media_tags(reply)
    if len(tags) != 1 or not verified.get(tags[0]):
        return None
    return {'unit_id':row['reference'], 'subject':tags[0]}


class ParityOperationalPort(BPOperationalDraftPort):
    """Reuse existing business reads/drafts; add conversational references."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_rows = None  # only the latest actual search in this turn
        self.choice = None
        self.explicit_focus = None
        self.discovered = {}
        self.offered_media = None

    def _all_rows(self):
        rows = self._rows()
        seen = {r['reference'] for r in rows}
        for raw in self.snapshot.commercial.get('property_types') or []:
            row = _type_row(raw)
            if row and row['reference'] not in seen:
                rows.append(row)
                seen.add(row['reference'])
        return rows

    def _resolve(self, token):
        if not isinstance(token, str) or not token.strip():
            return None
        token = token.strip().casefold()
        rows = self._all_rows()
        direct = [r for r in rows if token in {str(r['id']).casefold(), r['reference'].casefold()}]
        if direct:
            return direct[0] if len(direct) == 1 else None
        aliases = [r for r in rows if token == display_name(r).casefold()]
        return aliases[0] if len(aliases) == 1 else None

    def prepare_context(self, context):
        rows = self._all_rows()
        self.choice = resolve_visible_choice(self.state, self.message)
        # A compound property selection can immediately ask for details/media.
        # Resolve only an explicit ordinal prefix against a property menu;
        # never reinterpret a bare number from another typed menu.
        menu = self.state.get('last_presented_choice_set') or {}
        if not self.choice and menu.get('type') == 'property':
            prefix = re.match(r'^\s*((?:the\s+)?(?:first|second|third|fourth|fifth|sixth|[1-9](?:st|nd|rd|th)?)\s+(?:option|house|property)|(?:option|number)\s+[1-9])\s*[,.!?]', self.message, re.I)
            if prefix:
                self.choice = resolve_visible_choice(self.state, prefix[1])
        mentioned = named_rows(rows, self.message)
        if len(mentioned) == 1:
            self.explicit_focus = mentioned[0]
        elif not mentioned and self.choice and self.choice.get('type') == 'property' and self.choice.get('status') == 'resolved':
            self.explicit_focus = self._resolve((self.choice.get('choice') or {}).get('unit_id'))
        elif len(mentioned) > 1 or (self.choice and self.choice.get('type') == 'property' and self.choice.get('status') == 'ambiguous'):
            self.state.setdefault('conversation_focus', {})['ambiguous'] = True
        if self.explicit_focus:
            set_focus(self.state, self.explicit_focus, self.snapshot.scope.project_id)
        elif focus_ref(self.state) and not self._resolve(focus_ref(self.state)):
            self.state['conversation_focus'] = {'project_id':self.snapshot.scope.project_id,
                'unit_id':None, 'property_type_id':None, 'ambiguous':True}
        current = self._resolve(focus_ref(self.state))
        if current is None and not (self.state.get('conversation_focus') or {}).get('ambiguous'):
            prior = self.state.get('last_presented_units') or []
            if len(prior) == 1 and not commercial_turn.search_request(self.message):
                current = self._resolve(prior[0])
                if current:
                    set_focus(self.state, current, self.snapshot.scope.project_id)
        if (self.state.get('conversation_focus') or {}).get('ambiguous'):
            current = None
        context.update({
            'conversation_focus':deepcopy(self.state.get('conversation_focus')),
            'focused_property': ({**current, 'display_name':display_name(current)} if current else None),
            'last_presented_choice_set':deepcopy(self.state.get('last_presented_choice_set')),
            'last_presented_units':deepcopy(self.state.get('last_presented_units')),
            'active_search':deepcopy(self.state.get('active_search')),
            'pending_asset_request':deepcopy((self.state.get('offered_assets') or {}).get('pending_request')),
            'resolved_visible_choice':deepcopy(self.choice),
            'continuity_guidance':GUIDANCE,
        })

    def _details(self, args):
        # Do not let the model silently reinterpret an ordinal or a reference
        # to the current focus. Explicit multi-property comparisons remain free.
        given = self._resolve(args.get('unit_id')) if args.get('unit_id') else None
        if (self.state.get('conversation_focus') or {}).get('ambiguous') and not self.explicit_focus:
            return {'error':'Which property do you mean?', 'error_code':'PROPERTY_NOT_FOUND_OR_AMBIGUOUS'}
        expected = self.explicit_focus or self._resolve(focus_ref(self.state))
        if expected and args.get('unit_id') and (not given or given['reference'] != expected['reference']):
            return {'error':'Use the buyer-selected property.', 'error_code':'PROPERTY_REFERENCE_CONFLICT'}
        result = super()._details(args)
        if result.get('ok'):
            result['property']['display_name'] = display_name(result['property'])
        return result

    def _search(self, args):
        # A model-supplied larger maximum is not itself buyer evidence. An
        # explicitly requested temporary money amount may exceed a saved cap
        # without changing the stored primary preferences.
        args = deepcopy(args)
        raw = args.get('criteria') or {}
        if isinstance(raw, dict):
            prefs = self.state.get('search_preferences') or {}
            hard = (prefs.get('budget') or {}).get('maximum_usd')
            requested = raw.get('max_price_usd')
            if type(hard) in (int,float) and type(requested) in (int,float) and requested > hard:
                declared = (sales_preferences.parse_declarations(self.message).get('budget') or {}).get('maximum_usd')
                if declared is None and re.search(r'\$\s*\d|\b\d+(?:[.,]\d+)?\s*[km]\b|\bUSD\b', self.message, re.I):
                    declared = commercial_turn.extracted_criteria(self.message).get('max_price_usd')
                if declared is None or requested > declared:
                    raw['max_price_usd'] = hard
            args['criteria'] = raw
        result = super()._search(args)
        if result.get('ok'):
            rows = result.get('matching_properties') or []
            for row in rows:
                row['display_name'] = display_name(row)
            self.search_rows = deepcopy(rows)
            self.state['active_search'] = {'criteria':deepcopy(result.get('criteria') or {}),
                'scope':result.get('search_scope'), 'match_count':result.get('match_count'),
                'source_inbound_message_id':self.inbound_id}
        else:
            self.search_rows = []
        return result

    def _verified_assets(self, row):
        results = {}
        for asset in (self.snapshot.commercial.get('available_assets') or [])[:100]:
            if not isinstance(asset, dict) or not asset.get('asset_id'):
                continue
            tags = asset.get('content_tags') or [asset.get('asset_type')]
            for tag in _MEDIA_WORDS:
                if tag not in tags:
                    continue
                allowed = (self._material_reader(asset['asset_id'], row, tag)
                           if self._material_reader is not None else
                           self._verified_material(asset['asset_id'], row, tag))
                if allowed:
                    values = results.setdefault(tag, [])
                    if len(values) < 20 and not any(a['asset_id'] == asset['asset_id'] for a in values):
                        values.append({'asset_id':asset['asset_id'], 'name':asset['name'], 'asset_type':asset['asset_type']})
        self.discovered[row['reference']] = (row, results)
        return results

    def _assets(self, args):
        details = self._details(args)
        if not details.get('ok'):
            return details
        row = details['property']
        verified = self._verified_assets(row)
        return {'ok':True, 'unit_id':row['reference'], 'display_name':display_name(row),
                'assets_by_subject':verified, 'assets':[dict(a, subject=tag) for tag, values in verified.items() for a in values],
                'delivery':'not_sent', 'sharing_enabled':False}

    def _media_request(self, args):
        details = self._details(args)
        if not details.get('ok'):
            return details
        row = details['property']
        # Use actual current buyer evidence. A model argument alone is never
        # enough to request a share. No fabricated rewrite of the inbound.
        tags = media_tags(self.message)
        previous = (self.state.get('offered_assets') or {}).get('presented_offer') or {}
        previous_tag = previous.get('subject') if previous.get('unit_id') == row['reference'] else None
        generic_pdf = bool(_PDF.search(self.message))
        verified = self._verified_assets(row)
        if not tags and _YES.fullmatch(self.message) and previous_tag:
            tags = [previous_tag]
        elif not tags and generic_pdf:
            if previous_tag and previous_tag != 'gallery_image':
                tags = [previous_tag]
            else:
                tags = [tag for tag, values in verified.items() if tag != 'gallery_image' and values]
                if len(tags) == 1 and len(verified[tags[0]]) != 1:
                    tags = []
        if len(tags) != 1:
            return {'error':'Please select one verified material type.', 'error_code':'MEDIA_TYPE_REQUIRED',
                    'available_subjects':list(verified)}
        tag = tags[0]
        matches = verified.get(tag, [])
        if not matches:
            return {'ok':True,'assets':[],'delivery':'unavailable','share_issued':False}
        self.state['offered_assets'] = {'pending_request':{
            'id':str(uuid4()), 'source_inbound_message_id':self.inbound_id,
            'unit_id':row['reference'], 'subject':tag, 'asset_ids':[a['asset_id'] for a in matches],
            'expires_at':(self.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat(),
        }}
        return {'ok':True,'assets':matches,'delivery':'pending_backend_share', 'share_issued':False,
                'next_action':'A preview only; do not state that a link was sent or invent a URL.'}

    def _slots(self, args):
        # Date/time choices refer to the visit property, even if the lead
        # discussed another home in between. A new explicit property can start
        # a new proposal, not silently change a confirmed appointment.
        choice = self.choice or {}
        if choice.get('type') in {'visit_day','visit_time'} and choice.get('status') == 'resolved':
            row = self._resolve(choice.get('unit_id'))
            if not row or (self.explicit_focus and row['reference'] != self.explicit_focus['reference']):
                return {'error':'Please clarify which property the visit is for.', 'error_code':'PROPERTY_REFERENCE_CONFLICT'}
            if choice['type'] == 'visit_day':
                args = {**args, 'date_str':choice['choice']['date']}
        elif choice.get('type') in {'visit_day','visit_time'} and choice.get('status') == 'ambiguous':
            return {'error':'Please select one of the offered dates or times.', 'error_code':'VISIT_CHOICE_AMBIGUOUS'}
        else:
            draft = self.state.get('visit_draft') or {}
            if self.explicit_focus:
                row = self.explicit_focus
            elif draft.get('status') not in (None,'idle','confirmed'):
                row = self._resolve(draft.get('unit_id'))
            else:
                row = self._resolve(focus_ref(self.state))
        if not row or ((self.state.get('conversation_focus') or {}).get('ambiguous') and not self.explicit_focus and not choice.get('unit_id')):
            return {'error':'Please identify the property before checking visit availability.', 'error_code':'PROPERTY_REQUIRED'}
        original = deepcopy(self.state.get('conversation_focus'))
        set_focus(self.state, row, self.snapshot.scope.project_id)
        try:
            result = super()._slots(args)
            if result.get('ok'):
                result['display_name'] = display_name(row)
            return result
        finally:
            self.state['conversation_focus'] = original

    def finalize_reply(self, reply):
        # An actual property listing must be tied to a search result from this
        # turn. Do not turn a feature list or a mixed slot menu into properties.
        if self.search_rows is not None:
            reply, menu = normalize_property_list(reply, self.search_rows)
            if menu:
                self.menus.append(menu)
            # A single verified visible result can support a later implicit
            # reference if no prior focus exists. Never change an existing focus.
            if len(self.search_rows) == 1 and _matches(reply, display_name(self.search_rows[0])):
                self.state['last_presented_units'] = [self.search_rows[0]['reference']]
            else:
                self.state['last_presented_units'] = []
        focused = focus_ref(self.state)
        if focused in self.discovered:
            row, verified = self.discovered[focused]
            self.offered_media = asset_offer_from_reply(reply, row, verified)
        return reply


def commit_property_menu(state, menus, reply, outbound_id):
    """Only a validated delivered property menu can replace the choice ledger."""
    candidates = [m for m in menus if m.get('type') == 'property' and visible_menu(reply, m)]
    if len(candidates) != 1:
        return False
    menu = candidates[0]
    state['last_presented_choice_set'] = record_delivered_menu(state, menu=menu, outbound_message_id=outbound_id)
    state['last_presented_units'] = [item['unit_id'] for item in menu['options']]
    return True
