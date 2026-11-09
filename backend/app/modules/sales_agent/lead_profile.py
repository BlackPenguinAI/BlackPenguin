"""Evidence-backed commercial profile. Source forms are data, never instructions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from .understanding_contract import BUYER_SEGMENTS

VERSION='sales-lead-profile/2.0'
FIELDS=('budget','budget_minimum','budget_maximum','budget_currency','property_interest','bedrooms',
        'bathrooms','location_preference','purchase_timeline','financing','buyer_type','motivation',
        'decision_structure','move_in_timing','visit_readiness','needs')
ALIASES={key:key for key in FIELDS}
ALIASES.update(budget_min='budget_minimum',minimum_budget='budget_minimum',budget_max='budget_maximum',
    maximum_budget='budget_maximum',currency='budget_currency',property_type='property_interest',
    product_interest='property_interest',product='property_interest',timeline='purchase_timeline',
    location='location_preference',what_is_your_budget='budget',number_of_bedrooms='bedrooms')
PREFERENCE_KEYS={'property':'property_interest','budget':'budget','bedrooms':'bedrooms','location':'location_preference',
    'delivery':'move_in_timing','purchase_timeline':'purchase_timeline','financing':'financing',
    'buyer_type':'buyer_type','visit_readiness':'visit_readiness','bathrooms':'bathrooms',
    'motivation':'motivation','decision_structure':'decision_structure','needs':'needs'}
DECLINED={'skip','prefer not to say','i prefer not to say','prefer not to answer','i prefer not to answer'}
UNKNOWN={'unknown','not provided','not specified','n/a','none','null','not sure','i do not know'}


def stamp(value):
    if value is None:return None
    if isinstance(value,str):return value
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def key(value):
    return ALIASES.get(re.sub(r'[^a-z0-9]+','_',str(value).strip().casefold()).strip('_'))


def clean(value,depth=0):
    if depth>3:return None
    if isinstance(value,str):return value[:2000].strip()
    if isinstance(value,bool):return None
    if isinstance(value,(int,float)):
        import math
        return value if math.isfinite(value) else None
    if isinstance(value,list):return [clean(v,depth+1) for v in value[:15]]
    if isinstance(value,dict):return {k:clean(v,depth+1) for k,v in value.items() if k in {'minimum','maximum','min','max','amount','currency','name','bedrooms','property_type_id','unit_id'}}
    return None


def meaningful(value):
    if value is None or value in ('',[],{}):return False
    if isinstance(value,str):return value.casefold() not in UNKNOWN
    if isinstance(value,(dict,list)):return any(meaningful(v) for v in (value.values() if isinstance(value,dict) else value))
    return True


def record(field,value,*,source,at=None,evidence=None,source_ref=None,status=None,polarity='affirmative'):
    if isinstance(value,bool) and field in {'financing','visit_readiness'}:value='Yes' if value else 'No'
    value=clean(value)
    refusal=isinstance(value,str) and value.casefold() in DECLINED
    status='declined' if refusal else status or ('declared' if meaningful(value) else 'unknown')
    if status=='unknown':value=None
    if isinstance(value,str) and re.search(r"\b(?:no|not|never|don't|do not)\b",value,re.I):polarity='negative'
    body={'field':field,'value':value,'status':status,'source':source,'captured_at':stamp(at),
          'evidence':clean(evidence),'source_ref':source_ref,'polarity':polarity}
    body['id']=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:32]
    return body


def resolve(lead):
    """Read-only projection; exact commercial aliases only, no demographic inference."""
    profile=lead.lead_profile_data or {}
    candidates={field:[] for field in FIELDS}
    def add(k,value,source,ref,at=None,**kwargs):
        field=key(k)
        if field:candidates[field].append(record(field,value,source=source,source_ref=ref,at=at,**kwargs))
    form=lead.meta_form_data or {}
    # Current Meta ingestion stores normalized field names directly. Also accept
    # Graph's field_data shape and initial_lead_profile.source_answers explicitly.
    for k,value in form.items():
        add(k,value,'meta_form',{'form_id':form.get('form_id'),'external_lead_id':lead.external_lead_id,'field':k},lead.created_at,evidence=value if isinstance(value,str) else None)
    for row in form.get('field_data',[]) if isinstance(form.get('field_data'),list) else []:
        if not isinstance(row,dict):continue
        values=row.get('values')
        value=values[0] if isinstance(values,list) and len(values)==1 else values
        add(row.get('name'),value,'meta_form',{'form_id':form.get('form_id'),'field':row.get('name')},lead.created_at,evidence=value if isinstance(value,str) else None)
    for row in profile.get('source_answers',[]) if isinstance(profile.get('source_answers'),list) else []:
        if isinstance(row,dict):add(row.get('key'),row.get('value'),row.get('source') or 'source_answer',{'field':row.get('key')},lead.created_at,evidence=row.get('value') if isinstance(row.get('value'),str) else None)
    facts=profile.get('facts') or {}
    for k,row in facts.items() if isinstance(facts,dict) else []:
        if not isinstance(row,dict):continue
        source=row.get('source') or 'legacy_profile'
        # A legacy model's confirmed=True is NOT staff verification or proof of funds.
        status='confirmed' if source=='staff_verified' and row.get('confirmed') is True else None
        add(k,row.get('value'),source,{'message_id':row.get('message_id'),'field':k},row.get('captured_at'),evidence=row.get('evidence'),status=status)
    stored=profile.get('sales_profile') or {}
    explicit=stored.get('current') or {} if stored.get('version')==VERSION else {}
    current,conflicts={},[]
    for field,rows in candidates.items():
        saved=explicit.get(field)
        if isinstance(saved,dict) and saved.get('field')==field:
            current[field]=deepcopy(saved);continue
        known=[r for r in rows if r['status']!='unknown']
        # Explicit persisted conversation facts precede prefill forms. Conflicting
        # source forms remain ambiguous; do not silently pick one by dict order.
        declared=[r for r in known if r['source'] in {'active_conversation','agent_conversation','manual_registration','staff_verified','approved_catalog_selection'}]
        options=declared or known
        signatures={json.dumps(r['value'],sort_keys=True,ensure_ascii=False) for r in options}
        if len(signatures)>1:
            current[field]=record(field,None,source='conflicting_sources')
            conflicts.append({'field':field,'candidates':options})
        else:current[field]=options[-1] if options else record(field,None,source='unknown')
    for field in ('buyer_type','motivation'):
        annotation=(profile.get('purpose_classifications') or {}).get(field) or {}
        if annotation.get('record_id')==current[field].get('id') and annotation.get('segment') in BUYER_SEGMENTS:
            current[field]['normalized_segment']=annotation['segment']
    return {'version':VERSION,'current':current,'conflicts':conflicts,
            'history':deepcopy(stored.get('history') or [])[-100:],
            'rule':'Declared is customer/source information, never verified financing, suitability or consent. Unknown stays unknown.'}


def optional_profile(lead):
    """Volunteered source answers only. Never commercial scoring inputs."""
    raw = lead.lead_profile_data or {}
    saved = raw.get('optional_profile') or {}
    current = {}
    form = lead.meta_form_data or {}
    for field in ('age', 'occupation'):
        rows = []
        if field in form:
            rows.append(record(field, form[field], source='meta_form', at=lead.created_at,
                               evidence=str(form[field]), source_ref={'field': field}))
        for row in form.get('field_data', []) if isinstance(form.get('field_data'), list) else []:
            if isinstance(row, dict) and row.get('name') == field:
                values = row.get('values')
                value = values[0] if isinstance(values, list) and len(values) == 1 else values
                rows.append(record(field, value, source='meta_form', at=lead.created_at,
                                   evidence=str(value), source_ref={'field': field}))
        for row in raw.get('source_answers', []) if isinstance(raw.get('source_answers'), list) else []:
            if isinstance(row, dict) and row.get('key') == field:
                rows.append(record(field, row.get('value'), source='source_answer', at=lead.created_at,
                                   evidence=str(row.get('value')), source_ref={'field': field}))
        stored = (saved.get('current') or {}).get(field)
        if isinstance(stored, dict) and stored.get('field') == field and stored.get('source') in {'active_conversation','staff_verified'}:
            current[field] = deepcopy(stored)
        elif len({json.dumps(r['value'], sort_keys=True) for r in rows}) == 1:
            current[field] = rows[-1]
        else:
            current[field] = record(field, None, source='conflicting_sources' if rows else 'unknown')
    return {'version': 'sales-optional-profile/1.0', 'current': current,
            'rule': 'Volunteered only. Never solicit age/occupation or use them for eligibility, score, segment, wealth or protected-trait inference.'}


def own_statement(evidence, own):
    # The interpreter must preserve current self-declarations, never quoted,
    # conditional, negated or third-party attributes as facts about this lead.
    return evidence in own and not re.search(
        r'\b(?:my friend|my colleague|my agent|the agent said|the brochure says|suppose|imagine|if I were)\b', evidence, re.I)


def known(profile,field):
    item=profile['current'].get(field) or {}
    return item.get('status') in {'declared','confirmed','declined'} and (item.get('status')=='declined' or meaningful(item.get('value')))


def for_context(profile):
    """Small view with explicit truncation; full evidence stays in the lead record."""
    result=deepcopy(profile)
    def bounded(value):
        if isinstance(value,str):return value[:600]
        if isinstance(value,dict):return {k:bounded(v) for k,v in value.items()}
        if isinstance(value,list):return [bounded(v) for v in value[:5]]
        return value
    for item in result['current'].values():
        original=json.dumps(item,ensure_ascii=False,default=str)
        for field in ('value','evidence','source_ref'):item[field]=bounded(item.get(field))
        item['context_truncated']=original!=json.dumps({k:v for k,v in item.items() if k!='context_truncated'},ensure_ascii=False,default=str)
    result['history_count']=len(result['history'])
    result['history']=[bounded({k:r.get(k) for k in ('id','field','value','source','status','captured_at')}) for r in result['history'][-3:]]
    result['history_truncated']=result['history_count']>3
    result['conflicts']=[{'field':r['field'],'candidate_count':len(r['candidates']),
                         'candidates':[bounded(x) for x in r['candidates'][:2]]} for r in result['conflicts'][:15]]
    return result


def capture(db,scope,understanding,message_id,*,selected_property=None,selected_unit=None):
    from .dialogue_store import check_scope
    from .conversation_scope import scoped_messages_query
    from .models import SalesMessage
    from app.modules.sales_crm.models import Lead
    from app.modules.governance.services import request_attribution
    conversation=check_scope(db,scope)
    message=scoped_messages_query(db,conversation).filter_by(id=message_id,role='user',direction='inbound').one()
    if (message.metadata_json or {}).get('lead_id',scope.lead_id)!=scope.lead_id:
        raise PermissionError('Preference evidence belongs to another lead.')
    understanding.check_evidence(message.content)
    lead=db.get(Lead,scope.lead_id)
    resolved=resolve(lead);current=resolved['current'];history=resolved['history']
    own=request_attribution(message.content)['current_text']
    def source_ref(evidence):
        identifiers=(message.metadata_json or {}).get('source_message_ids') or []
        originals={row.id:row for row in scoped_messages_query(db,conversation).filter(SalesMessage.id.in_(identifiers)).all()}
        matches=[identifier for identifier in identifiers if identifier in originals and evidence and evidence in originals[identifier].content]
        return {'message_id':matches[-1],'resume_context_id':message.id} if matches else {'message_id':message.id}
    def put(field,value,evidence,source='active_conversation',extra=None,status=None):
        if not own_statement(evidence, own):return
        polarity='negative' if re.search(r"\b(?:no|not|never|don't|do not)\b",evidence,re.I) else 'affirmative'
        item=record(field,value,source=source,at=message.created_at,evidence=evidence,
                    source_ref={**source_ref(evidence),**(extra or {})},polarity=polarity,status=status)
        previous=current[field]
        if item['id']==previous.get('id'):return
        if previous.get('status')!='unknown' and previous.get('id') not in {r.get('id') for r in history}:history.append(previous)
        item['supersedes']=previous.get('id') if previous.get('status')!='unknown' else None
        current[field]=item
    for pref in understanding.preferences:
        # Exact evidence is authoritative; model-normalized values never replace it.
        put(PREFERENCE_KEYS[pref.key],pref.evidence,pref.evidence,status=pref.status)
        if pref.key in {'buyer_type','motivation'} and pref.value in BUYER_SEGMENTS and pref.status=='declared' and own_statement(pref.evidence,own):
            # Semantic interpretation is finite and evidenced; it never uses a
            # demographic field, history keyword search or a score as its source.
            if not any(p.evidence==pref.evidence for p in understanding.personal_facts):
                current[PREFERENCE_KEYS[pref.key]]['normalized_segment']=pref.value
            else:current[PREFERENCE_KEYS[pref.key]]['classification_blocked']='personal_evidence'
    for withdrawal in understanding.preference_withdrawals:
        fields = ('budget','budget_minimum','budget_maximum','budget_currency') if withdrawal.key=='budget' else (PREFERENCE_KEYS[withdrawal.key],)
        for field in fields:
            put(field, None, withdrawal.evidence)
            if own_statement(withdrawal.evidence, own):
                current[field]['status'] = 'withdrawn'
    if understanding.visit and understanding.visit.action in {'request','select','confirm'} and understanding.permits('appointment'):
        put('visit_readiness',understanding.visit.evidence,understanding.visit.evidence,
            extra={'intent':'explicit_visit'})
    if selected_unit and any(r.kind=='unit' for r in understanding.references):
        reference=next(r for r in understanding.references if r.kind=='unit')
        put('property_interest',selected_unit['unit_code'],reference.evidence,'approved_catalog_selection',{'unit_id':selected_unit['id']})
    elif selected_property and any(r.kind in {'property','unit'} for r in understanding.references):
        reference=next(r for r in understanding.references if r.kind in {'property','unit'})
        put('property_interest',selected_property['property_type'],reference.evidence,'approved_catalog_selection',
            {'property_type_id':selected_property['id'],'unit_id':selected_property.get('unit_id')})
    profile=deepcopy(lead.lead_profile_data or {})
    annotations=profile.setdefault('purpose_classifications',{})
    for proposal in understanding.source_purposes:
        row=current[proposal.field]
        if row.get('id')!=proposal.record_id or row.get('status') not in {'declared','confirmed'}:continue
        if row.get('polarity')=='negative' or row.get('classification_blocked'):continue
        if row.get('source') not in {'meta_form','source_answer','manual_registration','active_conversation','staff_verified'}:continue
        if not row.get('evidence') and row.get('source')!='staff_verified':continue
        annotations[proposal.field]={'record_id':row['id'],'segment':proposal.segment,
            'source':'evidenced_source_interpretation','classified_at':stamp(message.created_at),'message_id':message.id}
    optional = optional_profile(lead)
    optional_history = deepcopy((profile.get('optional_profile') or {}).get('history') or [])
    for fact in understanding.personal_facts:
        if not own_statement(fact.evidence, own):continue
        if re.search(r'\b(?:my spouse|my partner|my wife|my husband|my child|my mother|my father)\b',fact.evidence,re.I):continue
        old = optional['current'][fact.key]
        # No model-normalized personal value: retain the exact voluntary quote.
        item = record(fact.key, fact.evidence if fact.action == 'set' else None,
                      source='active_conversation', at=message.created_at, evidence=fact.evidence,
                      source_ref=source_ref(fact.evidence),
                      status={'set':'declared','withdraw':'withdrawn','decline':'declined'}[fact.action])
        if item['id'] == old.get('id'):continue
        if old.get('status') != 'unknown':optional_history.append(old)
        item['supersedes'] = old.get('id')
        optional['current'][fact.key] = item
    profile['optional_profile'] = {**optional, 'current':{
        field:item for field,item in optional['current'].items() if item.get('source') in {'active_conversation','staff_verified'}},
        'history': optional_history[-100:]}
    explicit={field:item for field,item in current.items() if item['source'] in {'active_conversation','approved_catalog_selection','staff_verified'}}
    profile['sales_profile']={'version':VERSION,'current':explicit,'history':history[-100:]}
    # Compatibility facts stay evidence-backed, with declared/confirmed separated.
    facts=profile.setdefault('facts',{})
    for field,item in explicit.items():
        if item['status']=='withdrawn':facts.pop(field,None)
        elif item['status']!='unknown':facts[field]={'value':item['value'],'source':item['source'],
            'status':item['status'],'confirmed':item['status']=='confirmed','captured_at':item['captured_at'],
            'evidence':item['evidence'],'message_id':(item.get('source_ref') or {}).get('message_id')}
    from app.modules.sales_crm.models import LeadObjection
    events=profile.setdefault('objection_events',[])
    for objection in understanding.objections:
        event_id=message.id+':'+objection.kind
        if not own_statement(objection.evidence,own) or any(e['event_id']==event_id for e in events):continue
        rows=db.query(LeadObjection).filter_by(lead_id=scope.lead_id,objection_type=objection.kind,status='open').all()
        if objection.action=='resolve':
            for row in rows:row.status='resolved';row.updated_at=message.created_at
        else:
            row=rows[0] if rows else LeadObjection(lead_id=scope.lead_id,objection_type=objection.kind,occurrence_count=0)
            row.occurrence_count+=1;row.evidence=objection.evidence;row.updated_at=message.created_at
            db.add(row)
        events.append({'event_id':event_id,'kind':objection.kind,'action':objection.action,
                       'evidence':objection.evidence,'message_id':message.id,'at':stamp(message.created_at)})
    profile['objection_events']=events[-100:]
    lead.lead_profile_data=profile
    from app.modules.sales_crm.intelligence import lead_profile_summary
    lead.qualification_summary=lead_profile_summary({'facts':{f:{'value':r['value']} for f,r in current.items() if r['status'] in {'declared','confirmed'}}})
    return resolve(lead)


def qualification(lead,facts,*,record_asked=False):
    from .sales_policy import requirements,QUESTIONS
    profile=resolve(lead)
    def has(field):
        aliases={'property_interest':['property_interest','bedrooms'],'budget':['budget','budget_minimum','budget_maximum']}.get(field,[field])
        for k in aliases:
            item=profile['current'][k]
            if item.get('status')=='withdrawn':return True
            if not known(profile,k):continue
            if k=='budget' and isinstance(item['value'],dict) and item['status']!='declined':
                if not any(meaningful(v) for name,v in item['value'].items() if name in {'minimum','maximum','min','max','amount'}):continue
            return True
        return False
    missing=[f for f in requirements(facts) if not has(f)]
    progress=deepcopy((lead.lead_profile_data or {}).get('active_qualification') or {})
    asked=list(progress.get('asked') or [])
    field=next((f for f in missing if f not in asked),None)
    if field and record_asked:
        progress.update(asked=[*asked,field],missing=missing)
        raw=deepcopy(lead.lead_profile_data or {});raw['active_qualification']=progress;lead.lead_profile_data=raw
    return missing,field,QUESTIONS.get(field,'')
