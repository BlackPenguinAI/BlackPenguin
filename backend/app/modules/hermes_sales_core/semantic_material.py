"""Read-only material discovery when the old delivery evidence is insufficient.

Hermes interprets the buyer's request. This adapter exposes the approved
catalog, never manufactures a share authorization or changes asset tags.
"""
from copy import deepcopy
import re


def discover(port, args, outcome, prior_offers, *, explicit_tags):
    """Enrich ambiguous/unavailable results with verified alternatives.

    Existing literal share authorization remains authoritative. Bare assent
    and generic 'documents' can draft a share in the old tool but the native
    effect cannot authorize it. In this live lane return discovery instead.
    """
    pending = (port.state.get('offered_assets') or {}).get('pending_request') or {}
    unsupported = (pending.get('source_inbound_message_id') == port.inbound_id
                   and not explicit_tags
                   and not (re.search(r'\bpdf\b', port.message, re.I)
                            and pending.get('subject') != 'gallery_image'
                            and len(pending.get('asset_ids') or []) == 1))
    ambiguous = outcome.get('error_code') == 'MEDIA_TYPE_REQUIRED'
    absent = outcome.get('ok') and outcome.get('delivery') == 'unavailable'
    if not (unsupported or ambiguous or absent):
        return outcome
    if unsupported:
        port.state['offered_assets'] = deepcopy(prior_offers)
    # The inherited read path uses the same scoped property resolution and
    # metadata-only approval checks, including channel and asset coverage.
    found = port._assets(args)
    if not found.get('ok'):
        return found
    verified = found.get('assets_by_subject') or {}
    port.semantic_media_discovery = deepcopy(verified)
    # Preserve the distinction: these are alternatives, not matches for the
    # requested type, and never an issued/authorized link.
    return {**found, 'assets': [], 'available_subjects': list(verified),
            'delivery': 'unavailable' if absent else 'not_sent',
            'share_issued': False, 'sharing_enabled': False,
            'next_action': ('Interpret the buyer request semantically using the approved categories in '
                            'assets_by_subject. Answer whether the requested type is available, '
                            'distinguish alternatives, and do not invent or claim delivery of a link. '
                            'For an actual share, ask the buyer to request the available material '
                            'by its specific type (photo gallery, brochure, floor plan or fact sheet) '
                            'if the current request does not authorize it.')}


def fallback_reply(verified, property_name=None):
    """Only used for a failed text response following verified read-only discovery."""
    labels = {'gallery_image': 'a photo gallery', 'brochure': 'a brochure',
              'floor_plan': 'a floor plan', 'unit_sheet': 'a fact sheet'}
    choices = [label for key, label in labels.items() if verified.get(key)]
    from .material_continuity import has_private_link
    name='this property'
    if (isinstance(property_name,str) and 0<len(property_name.strip())<=100 and
            '://' not in property_name and not has_private_link(property_name)):
        name=' '.join(property_name.split())
    if not choices:
        return f"I couldn't find an approved material for {name} right now. What other details would help?"
    return f'The approved materials for {name} include ' + ', '.join(choices) + '. Which would you like to see?'


def read_only_recovery_allowed(port, initial, *, sources, primary_snapshot):
    """No repairs to visits, preferences, searches or pending external effects."""
    if (len(sources) != 1 or primary_snapshot is not None or port.search_batches or port.slot_batches
            or port.comparison_batches or port.menus or port.prepared_visit):
        return False
    state = port.state
    # Only focus and the turn-local evidence marker can legitimately change
    # during a material read. Fail closed for all other changes.
    ignored = {'conversation_focus', '_active_source_message_id', 'last_presented_choice_set',
               'choice_set_initialized', 'offered_assets'}
    if any(state.get(k) != initial.get(k) for k in set(state) | set(initial) if k not in ignored):
        return False
    pending = (state.get('offered_assets') or {}).get('pending_request') or {}
    # Even an unchanged pending external effect is not a recovery lane.
    if pending.get('source_inbound_message_id') == port.inbound_id:
        return False
    return True


def safe_read_only_fallback(port, initial, *, sources, primary_snapshot):
    if (getattr(port,'semantic_media_discovery',None) is None or not
            read_only_recovery_allowed(port,initial,sources=sources,primary_snapshot=primary_snapshot)):
        return None
    # No hidden offer from an invalid model response can authorize a later turn.
    port.offered_media = None
    return fallback_reply(port.semantic_media_discovery,getattr(port,'semantic_media_property_name',None))


def align_contextual_search(port, result):
    """A search directly following the verified bedroom preference is not temporary.

    This is an evidence check against an already captured declaration, not a
    new language classifier. Do not relabel different or extra search filters.
    """
    evidence = getattr(port, 'contextual_preference', None) or {}
    bedrooms = (evidence.get('bedrooms') or {}).get('preferred')
    search = port.state.get('active_search') or {}
    if (type(bedrooms) is int and result.get('ok') and search.get('criteria') == {'bedrooms': bedrooms}
            and search.get('source_inbound_message_id') == port.inbound_id
            and (port.state.get('search_preferences') or {}).get('last_source_message_id') == port.inbound_id):
        search['scope'] = 'permanent'
        result['search_scope'] = 'permanent'
    return result
