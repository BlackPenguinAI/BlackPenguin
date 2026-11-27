"""Live commercial evidence helpers. No SDK storage, provider or calendar calls."""
from __future__ import annotations
import re


def approved_material_candidate(db, snapshot, asset_id, row, subject):
    """Discover approved metadata only; the API's _material_batch still verifies
    file integrity, encryption and the exact share before issuing anything.
    """
    from .bp_context import require_scoped_entities
    from .production_tools import _resolve_property
    from app.modules.projects.sales_asset_service import approved_for_turn
    from app.modules.projects.asset_coverage import matches
    from app.modules.sales_agent.commercial_context import _safe_asset_links
    from urllib.parse import urlsplit
    _, project, _, _ = require_scoped_entities(db, snapshot.scope)
    prop, unit, _ = _resolve_property(db, snapshot.scope, project, row['reference'], snapshot.channel)
    assets = approved_for_turn(db, project_id=snapshot.scope.project_id,
                              company_id=snapshot.scope.company_id, channel=snapshot.channel)
    asset = next((a for a in assets if a.id == asset_id), None)
    if asset is None or not any(x.get('coverage') == 'requested_tag' for x in matches(
            asset, property_id=prop, unit_id=unit, subject='photos' if subject == 'gallery_image' else subject)):
        return False
    source = asset.source
    if source and source.storage_path:
        return True  # candidate, NOT file validation or share authorization
    return bool(source and subject == 'gallery_image' and any(
        item['kind'] in {'photos', 'gallery_image'} and urlsplit(item['url']).scheme == 'https'
        for item in _safe_asset_links(asset)))


# Evidence boundary for the two observed natural declarations, not a new intent
# router. Existing preference parser remains authoritative for other utterances.
_INITIAL = re.compile(r"\s*(?:i[’']m|i am|we[’']re|we are) looking for (?:a |an )?([1-9]|1\d|20)[ -]bedroom(?:s)? (?:house|home|property|apartment)s?[.!]?\s*", re.I)
_ACCEPT = re.compile(r"\s*(?:yes[, ]+)?([1-9]|1\d|20)\s*bedrooms?\s*(?:(?:is|are|it[’']s|is also)\s*)?(?:ok(?:ay)?|fine|acceptable|works(?: for me)?)[.!]?\s*", re.I)
_ALT = re.compile(r'\b(?:open to|explor\w*|alternative\w*|adjust|consider\w*)\b', re.I)


def contextual_bedrooms(message, prior_state, prior_reply=None):
    """Only a first explicit preference or an acceptance of the immediately
    delivered no-match alternative. Never promote an arbitrary search or a
    model-supplied number to a primary preference.
    """
    existing = (prior_state.get('search_preferences') or {}).get('bedrooms') or {}
    initial = _INITIAL.fullmatch(message)
    if initial and existing.get('mode', 'unknown') == 'unknown':
        return {'bedrooms': {'mode': 'preferred', 'preferred': int(initial[1])}}
    accepted = _ACCEPT.fullmatch(message)
    if not accepted or not isinstance(prior_reply, str):
        return {}
    search = prior_state.get('active_search') or {}
    if search.get('match_count') != 0 or not _ALT.search(prior_reply):
        return {}
    n = int(accepted[1])
    if not re.search(rf'(?<!\d){n}\s*[- ]?\s*bedrooms?\b', prior_reply, re.I):
        return {}
    return {'bedrooms': {'mode': 'preferred', 'preferred': n}}


def live_preference_context(db, scope, conversation, inbound, prior_state):
    """Use only the immediate scoped accepted assistant reply, with a provider ID.
    Historical messages with an intervening buyer message cannot authorize assent.
    """
    from sqlalchemy import or_, and_
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    previous = scoped_messages_query(db, conversation).filter(or_(
        SalesMessage.created_at < inbound.created_at,
        and_(SalesMessage.created_at == inbound.created_at, SalesMessage.id < inbound.id),
    )).order_by(SalesMessage.created_at.desc(), SalesMessage.id.desc()).first()
    prior_reply = (previous.content if previous and previous.direction == 'outbound'
                   and previous.role == 'assistant' and previous.provider_message_id
                   and previous.status in {'sent', 'accepted', 'delivered', 'read'} else None)
    return contextual_bedrooms(inbound.content, prior_state, prior_reply)


def persist_contextual_preferences(db, scope, *, inbound_message_id):
    """Apply the existing CRM writer after a committed, scoped reply receipt.
    Re-derive contextual evidence from the preceding state, not model arguments.
    Return None for the established direct-preference lane.
    """
    from .production_tools import _load_live_turn, _authorize_tool, _write_profile, ProductionToolError
    from .bp_models import HermesSalesStateEvent
    from .bp_state_store import blank_state
    conversation, project, lead, inbound, run, reply, receipt, loaded = _load_live_turn(db, scope, inbound_message_id)
    if loaded.revision != receipt.revision or loaded.data != receipt.state_after:
        raise ProductionToolError('Newer state supersedes contextual preference evidence.')
    if receipt.revision == 1:
        prior = blank_state(scope)
    else:
        event = db.query(HermesSalesStateEvent).filter_by(**scope.__dict__, revision=receipt.revision-1).one_or_none()
        if not event:
            return None
        prior = event.state_after
    evidence = live_preference_context(db, scope, conversation, inbound, prior)
    if not evidence:
        return None
    _authorize_tool(db, run, 'update_search_preferences')
    preference = loaded.data.get('search_preferences') or {}
    saved = preference.get('bedrooms') or {}
    if preference.get('last_source_message_id') != inbound.id or any(saved.get(k) != v for k,v in evidence['bedrooms'].items()):
        raise ProductionToolError('Contextual preference does not match committed evidence.')
    fields = _write_profile(db, lead, inbound, {'bedrooms': saved['preferred']})
    run.output_snapshot = {**(run.output_snapshot or {}), 'native_live_profile': {
        'source_message_id': inbound.id, 'updated_fields': fields, 'evidence_kind': 'contextual_bedrooms'}}
    db.flush()
    return {'status':'persisted' if fields else 'unchanged','updated_fields':fields}
