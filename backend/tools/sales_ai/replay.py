"""Real coordinator/store/dispatcher replay with every external boundary offline.

This measures deterministic safety and persistence, never live-model quality or
T01-T26 acceptance. The full acceptance journeys remain pending their groups.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def interpretation(text, topic='inventory'):
    return {'version':'sales-understanding/1.0',
            'requests':[{'id':'request1','topic':topic,'subject':None,'polarity':'request','evidence':text}],
            'all_of':['request1'],'alternatives':[],'constraints':[],'references':[],'preferences':[],
            'requires_clarification':False,'clarification_question':None,'confidence':0.99}


def run_case(catalog, project_id, channel, text, responses, *, case_id, origin, monkeypatch):
    tests=Path(__file__).resolve().parents[2]/'tests'
    if str(tests) not in sys.path:sys.path.insert(0,str(tests))
    from sales_ai_support.sandbox import Sandbox, InboundHarness
    from sales_ai_support.trace import TurnTrace
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.dialogue_models import SalesDialogueEvent
    from app.modules.sales_crm.models import Meeting
    from app.modules.governance.models import HumanInterventionCase
    from .snapshot import BASE_COMMIT
    sandbox=Sandbox(catalog)
    try:
        harness=InboundHarness(sandbox,project_id,channel,monkeypatch,*responses)
        inbound,run=harness.turn(text)
        before=(len(harness.model.requests),len(harness.messenger.calls),sandbox.db.query(SalesDialogueEvent).count())
        harness.retry(inbound)
        after=(len(harness.model.requests),len(harness.messenger.calls),sandbox.db.query(SalesDialogueEvent).count())
        replies=harness.replies()
        failures=[]
        if harness.conversation.is_paused:failures.append('Unexpected pause')
        if not replies or not any(m.content.strip() for m in replies):failures.append('No persisted response')
        if not harness.messenger.calls:failures.append('No simulated dispatch acceptance')
        if sandbox.db.query(Meeting).count():failures.append('Unexpected appointment')
        if sandbox.db.query(HumanInterventionCase).count():failures.append('Unexpected intervention')
        if before!=after:failures.append('Retry changed inference/delivery/event counts')
        output=run.output_snapshot or {}
        recorded_error=run.error_code or output.get('error_code')
        if origin!='SYNTHETIC_FAILURE':
            if recorded_error or run.status in {'blocked','failed'}:
                failures.append('Ordinary commercial request reached an error fallback')
            entry=next(p for p in catalog['projects'] if p['project']['id']==project_id)
            if entry['property_types'] and not any(p['name'] in '\n'.join(m.content for m in replies) for p in entry['property_types']):
                failures.append('Ordinary inventory request did not mention an approved property')
        trace=TurnTrace(sandbox.clock,harness.project.company_id,harness.project.id,harness.lead.id,
                        harness.conversation.id,inbound.id,run.id,BASE_COMMIT,
                        configuration_id=run.prompt_configuration_id,model=run.model)
        trace.record('inbound',status='ok',evidence={'channel':channel,'fixture_origin':origin})
        trace.record('context',status='ok',evidence={'source_capture':catalog['captured_at'],'project_id':project_id})
        trace.record('understanding',status='failed' if output.get('error_code') else 'ok',evidence={'error_code':output.get('error_code'),'scripted_calls':len(harness.model.requests)})
        trace.record('persist',status='ok',evidence={'response_ids':[m.id for m in replies]})
        trace.record('dispatch',status='ok',evidence={'acceptances':len(harness.messenger.calls),'actual_provider_calls':0,'delivered_receipts':0})
        trace.record('complete',status='failed' if failures else 'ok',evidence={'retry_deduplicated':before==after,'safety_failures':failures})
        return {'id':case_id,'origin':origin,'channel':channel,'project_id':project_id,
                'passed_current_safety':not failures,'failures':failures,
                'recorded_engine':run.graph_version,'recorded_run_status':run.status,
                'recorded_error_code':recorded_error,
                'replies':[m.content for m in replies], 'trace':trace.export(),
                'new_flow_acceptance':'PENDING','model_quality_evaluated':False,'external_actions':0}
    finally:
        sandbox.close()


def run_suite():
    tests=Path(__file__).resolve().parents[2]/'tests'
    if str(tests) not in sys.path:sys.path.insert(0,str(tests))
    from sales_ai_support.sandbox import load_catalog, FIXTURES
    from pytest import MonkeyPatch
    real=load_catalog();synthetic=load_catalog('synthetic_catalog.json')
    history=json.loads((FIXTURES/'historical_cases_20261108.json').read_text())
    definitions=[]
    for case in history['cases']:
        if case['origin']!='HISTORICAL_OBSERVATION':continue
        for channel in ('sms','whatsapp'):
            definitions.append((real,case['project_id'],channel,case['inbound'],[interpretation(case['inbound'])],case['id']+':'+channel,'SCRIPTED_REPLAY_OF_HISTORICAL_TEXT'))
    for project in synthetic['projects']:
        for channel in ('sms','whatsapp'):
            text='Give me information'
            definitions.append((synthetic,project['project']['id'],channel,text,[interpretation(text)],project['fixture_key']+':'+channel,'SYNTHETIC'))
    for failure in ('invalid_json','timeout'):
        for channel in ('sms','whatsapp'):
            replies=['invalid JSON']*2 if failure=='invalid_json' else [TimeoutError('SYNTHETIC timeout')]*2
            definitions.append((synthetic,synthetic['projects'][0]['project']['id'],channel,'Give me information',replies,failure+':'+channel,'SYNTHETIC_FAILURE'))
    results=[]
    for catalog,pid,channel,text,responses,key,origin in definitions:
        with MonkeyPatch.context() as mp:
            try:
                results.append(run_case(catalog,pid,channel,text,responses,case_id=key,origin=origin,monkeypatch=mp))
            except Exception as error:
                results.append({'id':key,'origin':origin,'channel':channel,'project_id':pid,
                                'passed_current_safety':False,'failures':[type(error).__name__],
                                'new_flow_acceptance':'PENDING','model_quality_evaluated':False,'external_actions':0})
    from .snapshot import BASE_COMMIT
    return {'version':'sales-ai-baseline-replay/1.0','mode':'OFFLINE_COORDINATOR',
            'base_commit':BASE_COMMIT,'source_configuration':real.get('source_configuration'),
            'fixture_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURES.glob('*.json'))},
            'total':len(results),'passed_current_safety':sum(r['passed_current_safety'] for r in results),
            'model_quality_evaluated':False,'external_actions':0,'live_channel_acceptance':'NOT_RUN',
            't01_t26_acceptance':'PENDING_NEW_FLOW','results':results}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run_suite()
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f"offline_coordinator: {report['passed_current_safety']}/{report['total']}; model_quality_evaluated=false; external_actions=0; T01-T26=pending")
    return 0 if report['passed_current_safety']==report['total'] else 1


if __name__=='__main__':raise SystemExit(main())
