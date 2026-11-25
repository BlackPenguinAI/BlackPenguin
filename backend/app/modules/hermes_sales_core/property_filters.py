"""Composable search refinements, from validated Hermes v13.3.3 demo.

This is a fidelity reference for P01; no business-db writes or live tools.
USD/demo unit fields remain until the explicit BP adapter phase.
"""
from __future__ import annotations
import re
from typing import Any

_AREA=r'(\d+(?:[.,]\d+)?)\s*(?:m2|m²|sq\s*m|square met(?:er|re)s?)\b'
_BATH=r'(\d+(?:\.5)?)\s*(?:bathrooms?|baths?)\b'
_PARKING=r'(\d+)\s*(?:parking\s*(?:spaces?|spots?)|car\s*spaces?)\b'


def empty() -> dict:
    return {'revision':0,'min_area_sqm':None,'max_area_sqm':None,
            'min_bathrooms':None,'max_bathrooms':None,
            'min_parking_spaces':None,'kitchen_layout':None,
            'private_backyard':None,'relative_price_lt':None,'relative_price_gt':None,
            'source_unit_id':None,'source_message_id':None}


def parse(text: str, reference: dict | None = None) -> dict[str, Any]:
    t=(text or '').lower()
    changes={}
    area=re.search(_AREA,t,re.I)
    if area:
        value=float(area.group(1).replace(',','.'))
        if re.search(r'\b(?:larger than|more than|over|greater than|at least|minimum|bigger than|above)\b',t):
            changes['min_area_sqm']=value if re.search(r'\b(?:at least|minimum)\b',t) else value+0.001
        elif re.search(r'\b(?:less than|smaller than|under|below|at most|maximum)\b',t):
            changes['max_area_sqm']=value if re.search(r'\b(?:at most|maximum)\b',t) else value-0.001
    baths=re.search(_BATH,t,re.I)
    if baths and re.search(r'\b(?:want|need|looking|prefer|require|at least|at most|minimum|maximum|exactly)\b',t):
        value=float(baths.group(1))
        if re.search(r'\b(?:at most|maximum|no more than)\b',t):changes['max_bathrooms']=value
        else:
            changes['min_bathrooms']=value
            if re.search(r'\b(?:exactly|only)\b',t):changes['max_bathrooms']=value
    park=re.search(_PARKING,t,re.I)
    if park and re.search(r'\b(?:want|need|looking|prefer|require|at least|minimum)\b',t):
        changes['min_parking_spaces']=int(park.group(1))
    if re.search(r'\b(?:open[- ]plan|open)\s+kitchen\b|\bkitchen\s+(?:is|with|should be)\s+open\b',t):
        if re.search(r'\b(?:want|need|looking|prefer|require|with|has|have)\b',t):
            changes['kitchen_layout']='open'
    if re.search(r'\b(?:with|want|need|looking for|prefer|require)\s+(?:a\s+)?(?:private\s+)?(?:backyard|garden)\b',t):
        changes['private_backyard']=True
    if reference and re.search(r'\b(?:does|is|has|how)\s+H-\d{3}\b',t,re.I) and '?' in t:
        reference=None
    if reference:
        if re.search(r'\b(?:more|larger|bigger|greater)\s+(?:built\s+)?(?:area|space|square footage)\b|'
                     r'\b(?:something|one|house)\s+(?:larger|bigger|more spacious)\b',t):
            value=reference.get('area_sqm')
            if isinstance(value,(int,float)):changes['min_area_sqm']=float(value)+0.001
        if re.search(r'\b(?:less|smaller|lower)\s+(?:built\s+)?(?:area|space|square footage)\b|'
                     r'\b(?:something|one|house)\s+(?:smaller|less spacious)\b',t):
            value=reference.get('area_sqm')
            if isinstance(value,(int,float)):changes['max_area_sqm']=float(value)-0.001
        if re.search(r'\b(?:cheaper|less expensive|lower priced|lower price)\b',t):
            changes.update(relative_price_lt=int(reference['price_usd']),relative_price_gt=None)
        if re.search(r'\b(?:more expensive|higher priced|higher price)\b',t):
            changes.update(relative_price_gt=int(reference['price_usd']),relative_price_lt=None)
        if re.search(r'\b(?:fewer|less)\s+(?:bedrooms?|beds?)\b',t):
            changes['_bedrooms_maximum']=max(0,int(reference['bedrooms'])-1)
        if re.search(r'\b(?:more|extra)\s+(?:bedrooms?|beds?)\b',t):
            changes['_bedrooms_minimum']=int(reference['bedrooms'])+1
        if changes:changes['source_unit_id']=reference['unit_id']
    return changes


def update(state: dict, changes: dict, source_message_id: str | None) -> dict:
    if not changes:return {'ok':True,'changed_fields':[]}
    allowed=set(empty())-{'revision','source_message_id'}
    if set(changes)-allowed:return {'error':'Unsupported search refinement.'}
    current=state.setdefault('property_filters',empty())
    trial={**current,**changes}
    for key in ('min_area_sqm','max_area_sqm','min_bathrooms','max_bathrooms','min_parking_spaces'):
        value=trial[key]
        if value is not None and (not isinstance(value,(int,float)) or value<0 or value>100000):
            return {'error':f'Invalid search criterion {key}.'}
    for lo,hi in (('min_area_sqm','max_area_sqm'),('min_bathrooms','max_bathrooms')):
        if trial[lo] is not None and trial[hi] is not None and trial[lo]>trial[hi]:
            if lo in changes and hi not in changes:trial[hi]=None
            elif hi in changes and lo not in changes:trial[lo]=None
            else:return {'error':f'Inconsistent {lo} and {hi}.'}
    if trial==current:return {'ok':True,'changed_fields':[]}
    changed=[key for key in changes if trial.get(key)!=current.get(key)]
    trial['revision']=current.get('revision',0)+1
    trial['source_message_id']=source_message_id
    state.setdefault('property_filters_history',[]).append({
        'prior':dict(current),'changes':dict(changes),'source_message_id':source_message_id})
    state['property_filters_history']=state['property_filters_history'][-60:]
    state['property_filters']=trial
    return {'ok':True,'changed_fields':changed,'property_filters':trial}


def matches(unit: dict, criteria: dict | None) -> list[str]:
    f=criteria or empty();violations=[]
    if f.get('min_area_sqm') is not None and float(unit['area_sqm'])<float(f['min_area_sqm']):
        violations.append('Built area below requested minimum')
    if f.get('max_area_sqm') is not None and float(unit['area_sqm'])>float(f['max_area_sqm']):
        violations.append('Built area above requested maximum')
    bathrooms=float(unit['bathrooms'])
    if f.get('min_bathrooms') is not None and bathrooms<float(f['min_bathrooms']):
        violations.append('Fewer bathrooms than requested')
    if f.get('max_bathrooms') is not None and bathrooms>float(f['max_bathrooms']):
        violations.append('More bathrooms than requested')
    features=unit.get('confirmed_features') or {}
    if f.get('min_parking_spaces') is not None and float(features.get('parking_spaces') or 0)<float(f['min_parking_spaces']):
        violations.append('Insufficient parking spaces')
    if f.get('kitchen_layout') and features.get('kitchen_layout')!=f['kitchen_layout']:
        violations.append('Different kitchen layout')
    if f.get('private_backyard') is True and features.get('private_backyard') is not True:
        violations.append('No verified private backyard')
    if f.get('relative_price_lt') is not None and unit['price_usd']>=f['relative_price_lt']:
        violations.append('Not cheaper than the reference property')
    if f.get('relative_price_gt') is not None and unit['price_usd']<=f['relative_price_gt']:
        violations.append('Not more expensive than the reference property')
    return violations
