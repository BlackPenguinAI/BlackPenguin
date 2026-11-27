"""Model-facing material references and optional native delivery composition.

Opaque share credentials belong to the authorized provider lane, never Hermes.
This module performs no tool calls, authorization, persistence or inference.
"""
from __future__ import annotations

import re

MATERIALS = '[[AUTHORIZED_MATERIALS]]'
REDACTED = '[previous private material link omitted]'
# Match the entire URI (including query/fragment), or a relative bearer path.
# The actual share service uses the literal /projects/a/<opaque token> path.
_PRIVATE = re.compile(
    r'(?:https?://[^\s<>"\x27()\[\]]*?/projects/a/[^\s<>"\x27()\[\]]*|'
    r'/(?:[\w.-]+/)*projects/a/[^\s<>"\x27()\[\]]*)', re.I)
_ANY_URL = re.compile(r'https?://|www\.|://|/projects/a/', re.I)

GUIDANCE = (
    'Treat earlier private material links as delivery history, not reusable URLs. '
    'Use list_unit_assets to discover the focused property\'s approved resources; '
    'interpret requests such as blueprints or layout semantically, and distinguish '
    'a verified floor plan from other PDFs. Never invent or copy a link. '
    'When get_unit_media returns pending_backend_share, write the natural text '
    'for the requested material delivery with [[AUTHORIZED_MATERIALS]] alone on '
    'its own line where the backend will insert the authorized resources. '
    'Use the property name. An optional relevant next question may follow. '
    'Make the next question self-contained and name the actual resource or next step. '
    'Offer only other verified materials, without sending them or claiming a '
    'booking, delivery or other action already succeeded. For discovery only, '
    'answer normally without the marker. Do not force a question every turn.'
)


def has_private_link(value):
    return isinstance(value, str) and '/projects/a/' in value.casefold()


def redact(value):
    """Copy only the model-facing projection; leave original receipts intact."""
    if isinstance(value, str):
        return _PRIVATE.sub(REDACTED, value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def shared_materials(shared, approved_assets):
    """Project accepted material receipts into current approved catalog metadata.

    Share identifiers, source URLs, storage paths and bearer credentials are
    never model-facing. A provider acceptance is not device delivery.
    """
    if not isinstance(shared, dict) or not isinstance(approved_assets, list):
        return []
    rows=[];seen=set()
    for asset in approved_assets[:100]:
        if not isinstance(asset,dict):
            continue
        aid=asset.get('asset_id')
        receipt=shared.get(aid) if isinstance(aid,str) else None
        if (not isinstance(receipt,dict) or not receipt.get('share_id') or aid in seen):
            continue
        name=asset.get('name')
        if not isinstance(name,str) or not name.strip() or _ANY_URL.search(name):
            continue
        raw_tags=asset.get('content_tags') or [asset.get('asset_type')]
        tags=[t for t in raw_tags if isinstance(t,str) and t in {'gallery_image','brochure','floor_plan','unit_sheet'}] if isinstance(raw_tags,list) else []
        seen.add(aid)
        rows.append({'asset_id':aid,'name':name,'subjects':tags,'status':'provider_accepted'})
    return rows


def composition(text):
    """Accept one bounded, link-free model template, not a delivery action."""
    if not isinstance(text, str) or not 1 <= len(text) <= 900 or _ANY_URL.search(text):
        return None
    if text.count(MATERIALS) != 1 or MATERIALS not in [line.strip() for line in text.splitlines()]:
        return None
    if not text.replace(MATERIALS, '').strip() or REDACTED in text:
        return None
    before,after=text.split(MATERIALS)
    if not before.strip() or (after.strip() and continuation_question(after)!=after.strip()):
        return None
    return text.strip()


def continuation_question(text):
    """Keep an optional model-authored final question, not an unverified claim.

    Legacy responses lacking the explicit template can still retain a natural
    next step. This is presentation only, never a share or booking authorization.
    """
    if not isinstance(text, str) or _ANY_URL.search(text) or REDACTED in text:
        return None
    parts = re.split(r'(?<=[.!?])\s+|\n+', text.strip())
    question = parts[-1].strip() if parts else ''
    if (not 8 <= len(question) <= 280 or not question.endswith('?')
            or question.count('?') != 1 or _ANY_URL.search(question)
            or MATERIALS in question or REDACTED in question):
        return None
    return question


def render_delivery(approved_block, draft_copy=None, *, resource_block=None):
    """Insert only the native share service's already verified resource block."""
    if not isinstance(draft_copy, dict):
        return approved_block
    template = composition(draft_copy.get('template'))
    if template:
        # The native resource block includes the exact approved names and links.
        return template.replace(MATERIALS, resource_block if resource_block is not None else approved_block)
    question = standalone_question(draft_copy.get('question'))
    return approved_block + ('\n\n' + question if question else '')


def standalone_question(text):
    """Do not extract a dangling anaphor from discarded model prose."""
    question = continuation_question(text)
    if question and re.search(r"\b(?:that|this|it|them|those|these)\s*[?]$", question, re.I):
        return None
    return question
