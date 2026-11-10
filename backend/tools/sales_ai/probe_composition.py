"""Opt-in synthetic inference probe; read-only SQL, no lead delivery or DB writes."""
import argparse
import asyncio
import json
from sqlalchemy import text
from app.db.postgres import engine
from app.integrations.openrouter_client import generate_llm_response
from app.modules.sales_agent.commercial_composer import (
    Composition, VERSION, provider_error_details, response_schema, validate,
)


async def probe(key, model, schema, name):
    sample = {'version': VERSION, 'opening': 'direct',
              'blocks': [{'evidence_id': 'e0', 'wording': 'direct'}],
              'continuation_id': 'none', 'paragraphs': [['e0']]}
    messages = [{'role': 'system', 'content': 'Return exactly the supplied synthetic JSON object using the response schema.'},
                {'role': 'user', 'content': json.dumps(sample)}]
    try:
        raw = await generate_llm_response(key, model, messages,
            response_format={'type': 'json_schema', 'json_schema': {
                'name': 'sales_commercial_composition', 'strict': True, 'schema': schema}},
            temperature=.2, timeout_seconds=15, max_tokens=256, raise_on_error=True)
        validate(Composition.model_validate_json(raw),
                 [{'id': 'e0', 'required': True, 'wordings': {'direct': 'Synthetic evidence.'}}],
                 [{'id': 'none'}])
        return {'schema': name, 'result': 'accepted', 'http_status': 200}
    except Exception as exc:
        return {'schema': name, 'result': 'failed', 'error_code': type(exc).__name__,
                **provider_error_details(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--configuration-id', required=True)
    parser.add_argument('--model', default='openai/gpt-4o-mini')
    parser.add_argument('--compare-legacy', action='store_true',
                        help='Adds one synthetic inference with the original schema')
    args = parser.parse_args()
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            key = connection.execute(text('''
                SELECT openrouter_api_key FROM ai_configurations
                WHERE company_id = :company_id OR id = :configuration_id
                ORDER BY CASE WHEN company_id = :company_id THEN 0 ELSE 1 END
                LIMIT 1
            '''), vars(args)).scalar_one_or_none()
    if not key:
        raise SystemExit('No configured model credential was found.')
    async def run():
        results = []
        if args.compare_legacy:
            results.append(await probe(key, args.model, Composition.model_json_schema(), 'legacy'))
        results.append(await probe(key, args.model, response_schema(
            [{'id':'e0','required':True}], [{'id':'none'}]), 'corrected'))
        return results
    results = asyncio.run(run())
    print(json.dumps({'model': args.model, 'synthetic_only': True, 'database_writes': 0,
                      'lead_contacts': 0, 'results': results}, indent=2))
    return 0 if results[-1]['result'] == 'accepted' else 1


if __name__ == '__main__':
    raise SystemExit(main())
