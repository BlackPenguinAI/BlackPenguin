"""Six short scripted journeys exercising result-driven decisions, no buyer LLM."""
from . import continuity_battery as base
VERSION='sales-observation-battery/1.1'
SPECS={
 'obs_alternative':dict(project=1,property=1,access='selected',material='photos',date_style='numeric',visit='Can I visit {name}?',dialogue=[('discover','I am looking for a 1 bedroom home.'),('choose','{name}'),('material','Do you have photos of the property?'),('accept_material','Please send the brochure instead.'),('visit','Can I visit {name}?')]),
 'obs_mixed':dict(project=0,property=0,access='all',material='photos',date_style='month_day',visit='Can I visit {name}?',dialogue=[('discover','I am looking for a 4 bedroom home.'),('choose','{name}'),('material','Could you send photos or a brochure and explain the financing options?'),('visit','Can I visit {name}?')]),
 'obs_switch':dict(project=1,property=1,access='selected',material='floor_plan',date_style='numeric',visit='Can I visit {name}?',compare_switch=True,dialogue=[('discover','I am looking for a 2 bedroom home.'),('choose','{first}'),('switch','Actually I prefer {name} instead.'),('material','Please send the brochure for {name}.'),('visit','Can I visit {name}?')]),
 'obs_interrupt':dict(project=0,property=0,access='all',material='photos',date_style='month_day',visit='Can I visit {name}?',dialogue=[('discover','I am looking for a 4 bedroom home.'),('choose','{name}'),('visit','Can I visit {name}?'),('material','Before choosing a time, can you show me photos?'),('visit','Can I visit {name}?')]),
 'obs_time':dict(project=0,property=0,access='all',material='photos',date_style='month_day',visit='Can I visit {name}?',dialogue=[('discover','I am looking for a 4 bedroom home.'),('choose','{name}'),('visit',"I would like a visit any morning in the next seven days; use the property's timezone.")]),
 'obs_no_seller':dict(project=2,property=0,access='unassigned',material='photos',date_style='numeric',visit='Can I visit {name}?',dialogue=[('discover','I am looking for a 3 bedroom home.'),('choose','{name}'),('visit','Can I visit {name}?')]),
}
CASES=tuple(SPECS)

async def evaluate_case(db,manifest,key,budget,max_turns):
    prior=base.SPECS.get(key)
    base.SPECS[key]={**SPECS[key],'split':'observation'}
    try:result=await base.evaluate_case(db,manifest,key,budget,max_turns)
    finally:
        if prior is None:del base.SPECS[key]
        else:base.SPECS[key]=prior
    from .evaluation_checks import check
    for t in result['turns']:
        if (t.get('coordinator_graph') or {}).get('mode')=='graph-observe':
            audit=t.get('observation_loop') or {}
            t['checks'].append(check('observation_loop_valid',audit.get('status')=='PASS'))
            tools=audit.get('tools',[]);ids=[v['tool_id'] for v in tools]
            t['checks'].append(check('no_duplicate_or_writing_tools',len(ids)==len(set(ids)) and all(v.get('external_writes')==0 for v in tools)))
        if key=='obs_mixed' and t['action']=='material':
            t['checks'].append(check('independent_financing_answered',any(w in t['reply'].lower() for w in ('financing','mortgage','bank'))))
        if key=='obs_time':
            t['checks'].append(check('no_timezone_code_required',not any(w in t['reply'].lower() for w in ('provide an iana','enter your timezone','specify your timezone code'))))
    if key=='obs_no_seller':
        from app.modules.sales_agent.wait_models import SalesWaitRequest
        pending=db.query(SalesWaitRequest).filter_by(company_id=manifest['company_id'],lead_id=result['lead_id']).count()
        result['checks'].append(check('no_wait_created_without_lead_consent',pending==0))
    result['script_version']=VERSION
    return result
