"""One synthetic request to check provider acceptance of the new input contract."""
import argparse,asyncio,json
from .synthetic_lab import configuration
from .evaluation_guard import Budget,guard


async def probe(key,model):
    from app.modules.sales_agent.interpretation_input import Input,VERSION,schema,compile_input
    from app.modules.sales_agent.understanding_contract import Understanding
    from app.integrations.openrouter_client import generate_llm_response
    from app.modules.sales_agent.commercial_composer import provider_error_details
    base=Understanding.model_validate(dict(version='sales-understanding/1.0',requests=[],all_of=[],alternatives=[],constraints=[],references=[],preferences=[],requires_clarification=False,clarification_question=None,confidence=1.0)).model_dump(mode='json')
    for k in ['all_of','references','selected_reference_id','comparison']:base.pop(k)
    text='Show me Synthetic Studio.'
    base.update(version=VERSION,requests=[dict(topic='inventory',subject=None,polarity='request',evidence=text,target=dict(kind='property',expression='Synthetic Studio',evidence='Synthetic Studio'))],selection=None)
    sample=Input.model_validate(base).model_dump(mode='json')
    budget=Budget(1)
    try:
        with guard(budget):
            raw=await generate_llm_response(key,model,[{'role':'system','content':'Return exactly the supplied synthetic JSON object using the response schema.'},{'role':'user','content':json.dumps(sample)}],
                response_format={'type':'json_schema','json_schema':{'name':'sales_understanding','strict':True,'schema':schema(text)}},temperature=.2,timeout_seconds=20,max_tokens=1500,raise_on_error=True)
        Input.model_validate_json(raw) # A legacy-format reply does not prove provider acceptance.
        value,_=compile_input(raw,text);value.check_evidence(text)
        if not value.permits('inventory') or not value.references:raise ValueError('Probe contract output is incomplete.')
        return {'result':'accepted','http_status':200,'input_contract':VERSION,'provider_calls':budget.calls,'provider_usage':budget.usage}
    except Exception as exc:
        return {'result':'failed','error_code':type(exc).__name__,'provider_calls':budget.calls,**provider_error_details(exc)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--configuration-id',required=True);args=parser.parse_args()
    from app.db.postgres import engine
    credential=configuration(engine,args.configuration_id)
    result=asyncio.run(probe(credential['key'],credential['pack']['model']))
    print(json.dumps({'model':credential['pack']['model'],'configuration_version':credential['version_number'],'synthetic_only':True,'database_writes':0,'lead_contacts':0,'model_quality_evaluated':False,**result},indent=2))
    return 0 if result['result']=='accepted' else 2


if __name__=='__main__':raise SystemExit(main())
