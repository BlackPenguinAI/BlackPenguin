"""Reference binding to approved entities and complete, accepted outbound offers."""
from .execution import now as workflow_now

from datetime import datetime,timezone
import re
import unicodedata
from .understanding_contract import Offer
from .turn_context import latest_outbound,choice_index
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from .commercial_context import build_commercial_context
from app.modules.projects.models import Project


def normalized(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',value).casefold().replace('’',"'")).strip()


def accepted(message):
    return message.role=='assistant' and (message.status in {'sent','delivered','read','accepted'} or
        message.status in {'queued','sending','scheduled'} and bool(message.provider_message_id))


def offers_for_turn(db,conversation,state,*,now=None):
    from .dialogue_shadow import recorded_offers
    now=now or workflow_now(datetime).replace(tzinfo=timezone.utc)
    latest=latest_outbound(db,conversation.id,skip_language_holds=True)
    if not latest or latest.role!='assistant':return []
    current=recorded_offers(db,conversation,extended=False) if accepted(latest) else []
    group=(latest.metadata_json or {}).get('delivery_group') or {}
    complete=True
    if group.get('total',1)>1:
        messages=scoped_messages_query(db,conversation).filter_by(direction='outbound').all()
        parts=[m for m in messages if ((m.metadata_json or {}).get('delivery_group') or {}).get('key')==group.get('key')]
        indexes={((m.metadata_json or {}).get('delivery_group') or {}).get('part') for m in parts if accepted(m)}
        if indexes!=set(range(1,group['total']+1)):current=[];complete=False
    unit_ids=((latest.metadata_json or {}).get('unit_catalog_offer') or {}).get('unit_ids') or []
    if complete and accepted(latest) and unit_ids and len(unit_ids)<=200:
        project=db.get(Project,conversation.project_id)
        context=build_commercial_context(db,project=project,company_id=conversation.company_id,lead_id=conversation.lead_id,channel=conversation.channel)
        if set(unit_ids)<={r['id'] for r in context['inventory']}:
            current.append(Offer(kind='unit',message_id=latest.id,option_ids=unit_ids))
    kinds={o.kind for o in current}
    suspended=[]
    # Keep one original offer per kind. Its identity and expiry never restart.
    for offer in reversed(state.offers):
        if offer.kind in kinds or offer.expires_at and offer.expires_at<=now:continue
        row=scoped_messages_query(db,conversation).filter_by(id=offer.message_id).first()
        if row and accepted(row) and (row.metadata_json or {}).get('lead_id',conversation.lead_id)==conversation.lead_id:
            suspended.append(offer.model_copy(update={'status':'suspended'}));kinds.add(offer.kind)
    return [*current,*suspended]


class Resolver:
    def __init__(self,db,scope,state,*,now=None):
        self.db,self.scope,self.state=db,scope,state
        self.now=now or workflow_now(datetime).replace(tzinfo=timezone.utc)
        self.context=build_commercial_context(db,project=db.get(Project,scope.project_id),company_id=scope.company_id,lead_id=scope.lead_id)
        self.types={r['id']:r for r in self.context['property_types']}
        self.units={r['id']:r for r in self.context['inventory'] if r.get('unit_code')}

    def options(self,kind='property',ids=None):
        rows=self.units if kind=='unit' else self.types
        return [{'kind':kind,'id':key,'label':row['unit_code'] if kind=='unit' else row['property_type']}
                for key,row in rows.items() if ids is None or key in ids][:30]

    def bound(self,kind,identifier,message_id=None):
        if kind=='property':
            if identifier not in self.types:return None
            return {'kind':kind,'id':identifier,'property_id':identifier,'unit_id':None,'message_id':message_id}
        if kind=='unit':
            row=self.units.get(identifier)
            if not row:return None
            parents=[p['id'] for p in self.types.values() if p['property_type']==row.get('property_type')]
            return {'kind':kind,'id':identifier,'property_id':parents[0] if len(parents)==1 else None,'unit_id':identifier,'message_id':message_id}
        return {'kind':kind,'id':identifier,'message_id':message_id}

    def resolve(self,reference):
        from .dialogue_tasks import _resolve_legacy
        expression=normalized(reference.expression)
        kind=reference.kind
        def question(reason,options=None):return {'status':'clarification','reason':reason,'options':options if options is not None else self.options('unit' if kind=='unit' else 'property')}
        if kind in {'property','unit'}:
            rows=self.units if kind=='unit' else self.types
            label='unit_code' if kind=='unit' else 'property_type'
            names=[key for key,row in rows.items() if normalized(str(row[label]))==expression]
            if len(names)==1:return {'status':'resolved','value':self.bound(kind,names[0])}
            if expression in {'it','this one','that one','this property','that property','this unit','that unit','the same one'}:
                chosen=self.state.selected_unit_id if kind=='unit' else self.state.selected_property_type_id
                value=self.bound(kind,chosen) if chosen else None
                return {'status':'resolved','value':value} if value else question('no_selected_subject')
            if expression in {'the other','the other one','another one','another property','the other property','the other unit'}:
                previous=next((o for o in self.state.offers if o.kind==kind),None)
                selected=self.state.selected_unit_id if kind=='unit' else self.state.selected_property_type_id
                choices=[v for v in (previous.option_ids if previous else rows) if v!=selected and v in rows]
                if selected and len(choices)==1:return {'status':'resolved','value':self.bound(kind,choices[0],previous.message_id if previous else None)}
                return question('several_other_options',self.options(kind,choices))
        index=choice_index(reference.expression)
        ordinal_expression=re.sub(r'\b(?:property|unit|appointment|location|material|file)\b','',expression).strip()
        if index is None:index=choice_index(ordinal_expression)
        explicit_kind=bool(re.search(r'\b(?:property|unit|time|slot|appointment|location|file|material)\b',expression))
        candidates=[o for o in self.state.offers if (kind=='ambiguous' or o.kind==kind) and
                    (o.status=='current' or explicit_kind or kind=='appointment' and index is None)]
        if kind=='ambiguous' and len({o.kind for o in candidates})!=1:return question('ambiguous_offer_kind',[])
        if index is not None or kind=='appointment':
            # A bare ordinal can never resurrect an interrupted offer of another
            # kind. Explicit clock times may refer to a still-valid saved slot.
            if index is not None and not candidates:return question('no_current_offer')
            if kind=='unit' and index is not None:
                offer=next((o for o in candidates if o.kind=='unit'),None)
                value=self.bound('unit',offer.option_ids[index],offer.message_id) if offer and 0<=index<len(offer.option_ids) else None
            else:
                filtered=self.state.model_copy(update={'offers':candidates})
                ref=reference.model_copy(update={'expression':ordinal_expression}) if index is not None else reference
                value=_resolve_legacy(self.db,self.scope,filtered,ref,now=self.now)
                if value and value['kind'] in {'property','unit'}:value=self.bound(value['kind'],value['id'],value.get('message_id'))
            if value and value['kind']=='appointment':
                try:
                    at=datetime.fromisoformat(value['id']);at=at.replace(tzinfo=at.tzinfo or timezone.utc)
                    if at<=self.now:value=None
                except ValueError:value=None
            if value:return {'status':'resolved','value':value}
        if kind=='location':
            from .service import locations_for_project
            matches=[r for r in locations_for_project(self.db.get(Project,self.scope.project_id)) if expression in {normalized(r['label']),normalized(r['address'])}]
            if len(matches)==1:return {'status':'resolved','value':self.bound('location',matches[0]['address'])}
        if kind=='material':
            if expression in {'it','this file','that file','this pdf','that pdf','that brochure','these materials','those materials'}:
                offer=next((o for o in self.state.offers if o.kind=='material' and o.status=='current'),None)
                if offer and len(offer.option_ids)==1:
                    return {'status':'resolved','value':self.bound('material',offer.option_ids[0],offer.message_id)}
                return question('ambiguous_material_offer',[])
            matches=[a for a in self.context['available_assets'] if normalized(a.get('name') or '')==expression]
            if len(matches)==1:return {'status':'resolved','value':self.bound('material',matches[0]['asset_id'])}
        # Existing exact location/material resolution remains bounded by offers.
        return question('unknown_or_ambiguous_reference')
