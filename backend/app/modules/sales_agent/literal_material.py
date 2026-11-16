"""Current, single material request with an exact approved property owner."""
import re


def named_request(text,commercial):
    from app.modules.governance.services import request_attribution
    if request_attribution(text)['current_text']!=text:return None
    match=re.fullmatch(r"\s*(?:(?:please )?(?:send|show|share)(?: me| us)?|(?:can|could|would) you (?:send|show|share)(?: me| us)?) (?:the )?(brochure(?: PDF)?|PDF|photos?|pictures?|images?|floor plans?|blueprints?) (?:for|of) (.+?)[.!?]?\s*",text,re.I)
    if not match:return None
    owner=match[2].strip()
    matches=[p for p in commercial.get('property_types',[]) if p.get('property_type') and p['property_type'].casefold()==owner.casefold()]
    if len(matches)!=1:return None
    # Do not reinterpret an explicitly named individual unit or an asset title.
    if any(str(u.get('unit_code') or '').casefold()==owner.casefold() for u in commercial.get('inventory',[])):return None
    if any(str(a.get('name') or '').casefold()==owner.casefold() for a in commercial.get('available_assets',[])):return None
    subject='brochure' if re.search(r'pdf|brochure',match[1],re.I) else 'floor_plan' if re.search(r'floor|blueprint',match[1],re.I) else 'photos'
    return {'property_id':matches[0].get('id'),'name':matches[0]['property_type'],'quote':owner,'subject':subject}
