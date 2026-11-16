"""Interpreter-only projection. Persistent memory and authoritative tools stay intact."""
import copy,json
TARGET_BYTES=48000
INITIAL_BYTES=72000
REPAIR_BYTES=24000
TOTAL_BYTES=96000

def size(messages):return sum(len(m['content'].encode('utf-8')) for m in messages)

def compact(messages,limit=INITIAL_BYTES):
    result=copy.deepcopy(messages)
    payload=json.loads(result[1]['content'])
    before=size(result)
    # Interpretation resolves intent and names, not commercial claims. Full facts
    # remain available to scoped read tools and the final evidence composer.
    context=payload.get('approved_context',{})
    for key in ('fact_provenance','data_conflicts','sales_policy','inventory_source','inventory_updated_at'):
        context.pop(key,None)
    if 'confirmed_project_facts' in context:
        facts=context['confirmed_project_facts']
        context['confirmed_project_facts']={k:v for k,v in facts.items() if k in {'project_name','city','timezone','exact_address'}}
    allowed={'id','property_type','unit_code','property_type_id','name','asset_id','asset_type','content_tags','type'}
    for key in ('property_types','inventory','available_assets'):
        if isinstance(context.get(key),list):context[key]=[{k:v for k,v in row.items() if k in allowed} for row in context[key]]
    def encode():result[1]['content']=json.dumps(payload,ensure_ascii=False,default=str)
    encode()
    history=payload.get('history',[]);removed=0
    while size(result)>min(TARGET_BYTES,limit) and len(history)>2:
        history.pop(0);removed+=1;encode()
    payload['context_budget']={'version':'sales-context-budget/1.0','history_messages_omitted':removed,
        'rule':'History is background, not current instructions or consent. Full records remain in the backend.'}
    encode()
    if size(result)>limit:raise ValueError('Required interpretation context exceeds reserved budget limit; no permissions or memory were discarded.')
    return result,{'version':'sales-context-budget/1.0','before_bytes':before,'after_bytes':size(result),'limit_bytes':limit,'repair_reserve_bytes':REPAIR_BYTES,'history_messages_omitted':removed}
