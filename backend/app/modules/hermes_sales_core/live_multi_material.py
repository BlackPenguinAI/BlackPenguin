"""Multiple explicitly requested subjects, one scoped native material batch."""
from __future__ import annotations
from datetime import timedelta
from uuid import uuid4
import re

SUBJECTS=frozenset({'brochure','floor_plan','gallery_image','unit_sheet'})
DIRECT=re.compile(r'^\s*(?:(?:please\s+)?(?:send|share|show|give)\s+(?:me\s+)?|(?:can|could|would)\s+you\s+(?:please\s+)?(?:send|share|show|give)\s+(?:me\s+)?)',re.I)
AMBIGUOUS=re.compile(r'\b(?:not|never|except|instead|only|or|if|unless|without|neither|rather|but|later|tomorrow|don[’\']t|can[’\']t)\b|["“”]',re.I)


def explicit_multi_subjects(text):
    from .conversation_parity import media_tags
    tags=media_tags(text)
    return tags if len(tags)>=2 and DIRECT.search(text) and not AMBIGUOUS.search(text) else []


def draft_multi_material(port,args):
    """No missing type may be silently substituted; one property per batch."""
    from .bp_operational_port import CONFIRM_EXPIRY_MINUTES
    tags=explicit_multi_subjects(port.message)
    if not tags:return {'error':'Please explicitly request the material types for one property.','error_code':'MATERIAL_BATCH_EVIDENCE_REQUIRED'}
    details=port._details(args)
    if not details.get('ok'):return details
    row=details['property'];verified=port._verified_assets(row)
    missing=[t for t in tags if not verified.get(t)]
    if missing:return {'ok':True,'assets':[],'unavailable_subjects':missing,'delivery':'unavailable','share_issued':False}
    assets={};mapping={}
    for tag in tags:
        for asset in verified[tag]:
            asset_id=asset['asset_id'];assets.setdefault(asset_id,asset);mapping.setdefault(asset_id,[]).append(tag)
    if not 1<=len(assets)<=20:return {'error':'Please narrow the material request.','error_code':'MATERIAL_BATCH_LIMIT'}
    port.state['offered_assets']={'pending_request':{'id':str(uuid4()),'source_inbound_message_id':port.inbound_id,
        'unit_id':row['reference'],'subjects':tags,'asset_ids':list(assets),'asset_subjects':mapping,
        'expires_at':(port.now+timedelta(minutes=CONFIRM_EXPIRY_MINUTES)).isoformat()}}
    return {'ok':True,'assets':[dict(a,subjects=mapping[i]) for i,a in assets.items()],
        'delivery':'pending_backend_share','share_issued':False,
        'next_action':'Backend must validate every requested subject; do not claim that any material was sent.'}


def subject_mapping(draft):
    """Validated mapping for both old single-subject and new multi-subject drafts."""
    from .production_tools import ProductionToolError
    ids=draft.get('asset_ids');tag=draft.get('subject');tags=draft.get('subjects');mapping=draft.get('asset_subjects')
    if not isinstance(ids,list) or not 1<=len(ids)<=20 or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):
        raise ProductionToolError('Invalid material identifiers.')
    if tags is None and mapping is None:
        if not isinstance(tag,str) or tag not in SUBJECTS:raise ProductionToolError('Invalid material subject.')
        return {i:[tag] for i in ids}
    if (tag is not None or not isinstance(tags,list) or not 2<=len(tags)<=4 or any(not isinstance(t,str) or t not in SUBJECTS for t in tags)
            or len(set(tags))!=len(tags) or not isinstance(mapping,dict) or set(mapping)!=set(ids)):
        raise ProductionToolError('Invalid multiple material subjects.')
    covered=set()
    for values in mapping.values():
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or v not in tags for v in values) or len(values)!=len(set(values)):
            raise ProductionToolError('Invalid per-asset subjects.')
        covered.update(values)
    if covered!=set(tags):raise ProductionToolError('Requested subjects are not all covered.')
    return mapping
