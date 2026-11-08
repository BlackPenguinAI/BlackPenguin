"""Explicitly import approved catalog data and six reviewed benign incident cases.

The complete private export is an INPUT, never a checked-in fixture. Unknown
messages, raw prompts, webhook payloads and lead/contact rows are not imported.
"""
import argparse
import hashlib
import json
from pathlib import Path
from .snapshot import build_catalog, read_snapshot

# Explicitly reviewed incoming texts. Do not broaden this into a chat exporter.
INCIDENTS = [
    ('H01','f5be7f18-18a9-4bfa-bb80-c701754ccc4e','efa3b2c0-1347-4698-9152-ce322b54d5ea','Hello! Yes I would like more information'),
    ('H02','8976d198-e9b0-4c7b-91b7-ecbf4a704b0e','d1bf0827-9d85-497e-9084-7ba1ab63a332','Hello, I’m looking for a 3 bedroom house'),
    ('H03','9531db0e-fabc-4f13-a126-b2c413fd8dc2','615ff69a-edeb-44e7-998f-12a5e90f6ad8','I would like to he information about propertied'),
    ('H04','70100413-bdbb-4e7e-a539-8af37bc79046','715a7ba0-e2fb-46d0-9e8a-ee50bbcd70c7','I would like to get information about properties'),
    ('H05','275b18ca-52b0-4b5f-826e-fcc0c9813287','0a3e16e7-b3bd-420e-8b2f-c4c62bd3966e','Give me information about the properties you have available'),
    ('H06','9ad8e1f4-f4f5-4e06-afcf-a7a9f4417b24','07f4271e-95d2-4e22-bfa7-5a286a7343b5','I am looking for a 2 bedroom'),
]


def build_history(manifest, rows):
    runs={r['id']:r for r in rows.get('agent_runs',[])}
    messages={r['id']:r for r in rows.get('sales_messages',[])}
    conversations={r['id']:r for r in rows.get('sales_conversations',[])}
    cases=[]
    for case_id,run_id,message_id,reviewed_text in INCIDENTS:
        run,message=runs.get(run_id),messages.get(message_id)
        if not run or not message:
            cases.append({'id':case_id,'origin':'MISSING','source_run_id':run_id,'source_message_id':message_id})
            continue
        if message.get('content') != reviewed_text or run['conversation_id'] != message['conversation_id']:
            raise ValueError('Reviewed incident identity/content changed; manual review is required.')
        conv=conversations.get(message['conversation_id'])
        if not conv:
            raise ValueError('Incident conversation is missing.')
        output=run.get('output_snapshot') or {}
        trace=(run.get('input_snapshot') or {}).get('turn_trace') or {}
        policy=output.get('response_policy_trace') or {}
        cases.append({
            'id':case_id,'origin':'HISTORICAL_OBSERVATION','source_run_id':run_id,'source_message_id':message_id,
            'company_id':conv['company_id'],'project_id':conv['project_id'],'conversation_id':conv['id'],
            'channel':conv['channel'],'inbound':reviewed_text,'occurred_at':message['created_at'],
            'historical_code_commit':trace.get('code_commit'),'historical_engine':run.get('graph_version'),
            'historical_model':run.get('model'),'recorded_run_status':run.get('status'),
            'observed_error_code':run.get('error_code') or output.get('error_code'),
            'observed_reply':output.get('reply'),
            'intent_contract_issues':policy.get('intent_contract_issues') or [],
            'policy_violations':output.get('policy_violations') or [],
            'escalation_reason':(policy.get('escalation') or {}).get('reason'),
            'approved_revision':(trace.get('approved_context') or {}).get('approved_revision'),
            'desired_acceptance':'Answer the commercial request without pausing, booking or creating a security incident.',
            'acceptance_status':'PENDING_NEW_FLOW',
        })
    return {'version':'sales-ai-historical/1.0','captured_at':manifest.get('generated_at'),
            'snapshot_commit':manifest.get('app_commit_sha'),
            'note':'Historical failures are not claims that the same failure reproduces on current main. No missing prompt, stack trace or screenshot has been invented.',
            'cases':cases}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    manifest,rows,_=read_snapshot(args.snapshot)
    catalog=build_catalog(manifest,rows,snapshot_sha256=hashlib.sha256(args.snapshot.read_bytes()).hexdigest())
    history=build_history(manifest,rows)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,value in [('real_catalog_20261108.json',catalog),('historical_cases_20261108.json',history)]:
        (args.output_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(f"Fixture import complete: {len(catalog['projects'])} catalog projects; {sum(c['origin']=='HISTORICAL_OBSERVATION' for c in history['cases'])} reviewed historical cases; external_actions=0")
    return 0


if __name__=='__main__':
    raise SystemExit(main())
