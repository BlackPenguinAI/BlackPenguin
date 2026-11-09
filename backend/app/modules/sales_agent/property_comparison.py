"""Read-only comparisons over approved, scoped data. Missing is never zero."""
import math
import re
from typing import Literal
from pydantic import Field
from .understanding_contract import StrictModel, Comparison, Task
from .dialogue_tasks import restricted


class Target(StrictModel):
    kind: Literal['property','unit']
    property_id: str | None = None
    unit_id: str | None = None


class ComparisonRead(StrictModel):
    directive: Comparison
    targets: list[Target] = Field(default_factory=list,max_length=21)
    unresolved: bool = False


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):return None
    return float(value) if value >= 0 else None


def render(query, context, state, holds):
    """Return safe wording plus the ordered IDs actually shown as options."""
    d = query.directive
    types = {row['id']:row for row in context['property_types']}
    units = {row['id']:row for row in context['inventory'] if row.get('unit_code')}
    targets = query.targets
    if d.include_all:
        targets = [Target(kind='property',property_id=identifier) for identifier in types]
        if d.all_kind == 'unit':
            targets=[]
            for identifier,row in units.items():
                parents=[p['id'] for p in types.values() if p['property_type']==row.get('property_type')]
                targets.append(Target(kind='unit',unit_id=identifier,property_id=parents[0] if len(parents)==1 else None))
    if query.unresolved:
        return 'I need the property options to make this comparison.', [], []
    rows, seen = [], set()
    for target in targets:
        identifier = target.unit_id if target.kind == 'unit' else target.property_id
        signature = (target.kind,identifier)
        if signature in seen:continue
        seen.add(signature)
        row = (units if target.kind == 'unit' else types).get(identifier)
        if not row:
            return 'A requested option is no longer in the approved catalog.', [], []
        rows.append((target,row))
    if len(rows) < (1 if d.operation != 'compare' else 2):
        return 'I need the property options to make this comparison.', [], []
    criteria = ['bedrooms','bathrooms','area','features'] if 'general' in d.criteria else list(d.criteria)
    topics = {'price':'pricing','availability':'inventory','kitchen':'property_details','features':'property_details',
              'bedrooms':'property_details','bathrooms':'property_details','area':'property_details'}
    def permitted(target, criterion):
        # Catalog permission cannot bypass a price/inventory/property prohibition.
        for topic in {'catalog',topics[criterion]}:
            task = Task(id='comparison-read',topic=topic,status='pending',
                        property_id=target.property_id,unit_id=target.unit_id)
            if topic in holds or restricted(state,task):return False
            if target.kind=='unit' and not target.property_id and any(
                c.topic.value==topic and c.property_id and c.unit_id is None for c in state.property_constraints):return False
        return True
    def value(target,row,c):
        if not permitted(target,c):return 'held for Sales review',None,None
        is_unit = target.kind=='unit'
        if c in {'bedrooms','bathrooms'}:
            v=number(row.get(c));return (f'{v:g}' if v is not None else 'unconfirmed'),v,c
        if c=='availability':
            v=number(row.get('available_units')) if not is_unit and row.get('inventory_updated_at') else None
            if is_unit:
                return ('last recorded status: '+str(row['status']) if row.get('inventory_updated_at') and row.get('status') else 'unconfirmed'),None,None
            return (f'{v:g} last confirmed units' if v is not None else 'unconfirmed'),v,c
        if c=='price':
            low=number(row.get('price') if is_unit else row.get('starting_price'))
            high=low if is_unit else number(row.get('maximum_price'))
            currency=row.get('currency')
            if low is None or not currency:return 'unconfirmed',None,None
            label=f'{low:,.2f}' if high==low else f'{low:,.2f}–{high:,.2f}' if high is not None else f'from {low:,.2f}'
            return label+' '+currency,low if high==low else None,currency
        if c=='area':
            low=number(row.get('area') if is_unit else row.get('area_min'))
            high=low if is_unit else number(row.get('area_max'))
            # Units have no area-unit column: do not invent a dimension from a parent.
            unit=row.get('area_unit')
            if low is None:return 'unconfirmed',None,None
            label=f'{low:g}' if high in {None,low} else f'{low:g}–{high:g}'
            display=label+' '+str(unit or '(unit unconfirmed)')
            scale={'m2':1,'m²':1,'sqm':1,'sq m':1,'ft2':.09290304,'ft²':.09290304,'sq ft':.09290304,'sqft':.09290304}.get(str(unit).casefold())
            return display,low*scale if scale and high==low else None,'square_metres' if scale else None
        features=[v for v in row.get('features',[]) if isinstance(v,str)]
        if c=='kitchen':
            features=[v for v in features if 'kitchen' in v.casefold()]
            description=row.get('description')
            if isinstance(description,str):features.extend(v.strip()[:300] for v in re.split(r'[.!?]\s+',description) if 'kitchen' in v.casefold())
        if d.feature:
            needle=re.findall(r'[a-z0-9]+',d.feature.casefold())
            features=[v for v in features if needle and all(re.search(r'\b'+re.escape(token)+r'\b',v,re.I) for token in needle)]
        return '; '.join(v[:200] for v in features[:3]) if features else 'unconfirmed',None,None
    measurements={c:[value(t,r,c) for t,r in rows] for c in criteria}
    lines=[]
    shown=rows[:12]
    for i,(target,row) in enumerate(shown):
        label='Unit '+row['unit_code'] if target.kind=='unit' else row['property_type']
        lines.append(f'{i+1}. {label}: '+ '; '.join(c+': '+measurements[c][i][0] for c in criteria)+'.')
    if len(rows)>12:lines.append(f'Showing 12 of {len(rows)} approved options; ask for a narrower comparison.')
    if d.operation!='compare':
        c=criteria[0];values=measurements[c]
        comparable=all(v[1] is not None for v in values) and len({v[2] for v in values})==1
        if comparable:
            extreme=(max if d.operation=='maximum' else min)(v[1] for v in values)
            names=[('Unit '+r['unit_code'] if t.kind=='unit' else r['property_type']) for (t,r),v in zip(rows,values) if math.isclose(v[1],extreme,rel_tol=1e-9,abs_tol=1e-9)]
            lines.append(('Tie for ' if len(names)>1 else '')+('highest' if d.operation=='maximum' else 'lowest')+' '+c+' among these approved records: '+', '.join(names)+'.')
        else:lines.append('I cannot reliably rank these options: values, exact ranges or comparable currencies/area units are missing or restricted.')
    # Query coverage isn't an assertion that unsupplied inventory is unavailable.
    lines.append('This compares approved records; unconfirmed values do not mean zero or unavailable.')
    return '\n'.join(lines),[t.property_id for t,_ in shown if t.kind=='property'],[t.unit_id for t,_ in shown if t.kind=='unit']
