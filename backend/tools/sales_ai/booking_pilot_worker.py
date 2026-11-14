"""Disposable subprocess entry point for the six-case booking iteration."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch


def run(options_path, output):
    import app.db.base
    from app.db.postgres import Base, engine, SessionLocal
    from app.core.config import settings
    from app.modules.ai_core.models import AIConfiguration, PromptVersion
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from .synthetic_fixtures import seed
    from .synthetic_lab_worker import bundle
    from .evaluation import encode
    from .evaluation_checks import check, error_details, sanitize
    from .evaluation_guard import Budget, guard
    from .evaluation_worker import save_reports
    from .booking_pilot import CASES, evaluate_case, team
    path=Path(options_path);output=Path(output);options=json.loads(path.read_text())
    continuity=options.get('suite')=='continuity-battery'
    needs=options.get('suite')=='needs-discovery'
    compact=options.get('suite')=='compact-battery'
    closing=options.get('suite')=='closing-point'
    commercial=options.get('suite')=='commercial-point'
    if commercial:
        from .commercial_pilot import CASES,evaluate_case,prepare

    if closing:
        from .closing_pilot import CASES,evaluate_case
    if compact:
        from .compact_battery import CASES,evaluate_case,PERSONAS,SPECS,VERSION,summarize
        all_cases=CASES
        selection=options.get('case_selection')
        if selection and (len(set(selection))!=len(selection) or set(selection)-set(CASES)):
            raise ValueError('Invalid compact case selection.')
        CASES=tuple(selection or CASES)
    if needs:
        from .needs_discovery import CASES,evaluate_case,VERSION
        selection=options.get('case_selection')
        if selection and (len(set(selection))!=len(selection) or set(selection)-set(CASES)):raise ValueError('Invalid needs discovery selection.')
        CASES=tuple(selection or CASES)
    if continuity:
        from .continuity_battery import CASES,evaluate_case,VERSION,SPECS
        selection=options.get('case_selection')
        if selection and (len(set(selection))!=len(selection) or set(selection)-set(CASES)):raise ValueError('Invalid continuity selection.')
        CASES=tuple(selection or CASES)
    if engine.dialect.name!='sqlite' or not engine.url.database or Path(engine.url.database).parent!=path.parent:
        raise PermissionError('Booking iteration requires its private SQLite database.')
    Base.metadata.create_all(engine)
    credential=options['credential'];budget=Budget(options['max_calls'])
    report={'version':VERSION if compact or needs or continuity else 'sales-closing-point/1.0' if closing else 'sales-commercial-point/1.0' if commercial else 'sales-booking-point/1.0','synthetic_only':True,'production_database_writes':0,
        'lead_contacts':0,'provider_calls':0,'lead_model':None,'judge_model':None,'commit':settings.APP_COMMIT_SHA,'cases':[],
        'limitations':['Google Calendar integration and transport delivery are not exercised.',
            'Simulation selects the first eligible seller, not the production round-robin cursor.',
            'SQLite does not verify PostgreSQL concurrent-booking locks.',
            'Public availability wording requires human review. No notification is scheduled.',
            'Focused cases do not represent all eight buyer segments.']}
    if compact:
        report.update(defined_scenario_count=len(all_cases),selected_cases=list(CASES),is_full_battery=len(CASES)==len(all_cases),
            expected_bookings=sum(SPECS[k]['goal']=='booked' for k in CASES))
        report['limitations'][-1]='One explicit-motivation persona per segment plus one unknown; this is not exhaustive segment coverage.'
        report['limitations'].append('Material links resolve only inside the disposable database. Public HTTP/auth middleware is not exercised; exported links expire with the laboratory.')
    def only_local(connection,*args):
        if connection.engine is not engine:raise PermissionError('Non-lab database access blocked.')
    event.listen(Engine,'before_cursor_execute',only_local)
    try:
        with SessionLocal() as db:
            with guard(Budget(0)):
                manifest=seed(db,output/'materials')
                if commercial:prepare(db,manifest)
            report.update(company_name=manifest['company_name'],company_id=manifest['company_id'],project_count=3,property_count=6,
                project_name=manifest['projects'][0]['name'])
            if options['prepare_only']:
                report['team']=[] if closing or compact or needs or continuity else team(db,manifest,'all_projects',datetime.utcnow())
                report.update(status='PREPARED',model_quality_evaluated=False,scenario_count=len(CASES),scenarios=list(CASES))
            else:
                db.add(AIConfiguration(id=credential['id'],company_id=None,openrouter_api_key=credential['key'],agent_ventas=credential['pack']))
                db.add(PromptVersion(id=credential['version_id'],company_id=None,agent_key='sales',version_number=credential['version_number'],
                    is_published=True,configuration=credential['pack'],published_at=datetime.fromisoformat(credential['published_at']) if isinstance(credential['published_at'],str) else credential['published_at']))
                db.commit()
                from app.modules.sales_agent.turn_configuration import digest
                report.update(sales_model=credential['pack']['model'],configuration_version=credential['version_number'],configuration_sha256=digest(credential['pack']))
                for scenario in CASES:
                    budget.maximum=budget.calls+options['max_calls']//len(CASES)
                    try:
                        with guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
                            case=asyncio.run(evaluate_case(db,manifest,scenario,budget,options['max_turns']))
                        report['cases'].append(case)
                    except Exception as exc:
                        db.rollback();report['cases'].append({'case':scenario,'turns':[],'checks':[check('case_completed',False)],**error_details(exc)})
                if compact:
                    report['actual_bookings']=sum(len(c.get('meetings',[])) for c in report['cases'])
                    report['case_results']=summarize(report['cases'])
                    report['cost_reporting_complete']=budget.usage['responses_with_cost']==budget.calls
                if continuity:
                    report.update(overall_dialogue_quality='NOT_EVALUATED',quality_scope='Continuity, material ownership and first-booking checks only; human review remains necessary.',cost_reporting_complete=budget.usage['responses_with_cost']==budget.calls)
                    report['split_results']={split:{'cases':sum(c.get('split')==split for c in report['cases']),'passed':sum(c.get('split')==split and all(k['status']=='PASS' for t in c.get('turns',[]) for k in t.get('checks',[])) and all(k['status']=='PASS' for k in c.get('checks',[])) for c in report['cases'])} for split in ('development','transfer','resumption','contextual')}
                if needs:
                    report.update(overall_dialogue_quality='NOT_EVALUATED',quality_scope='Needs-first checks only; no integral dialogue certification.',cost_reporting_complete=budget.usage['responses_with_cost']==budget.calls)
                report.update(provider_calls=budget.calls,provider_usage=budget.usage,scenario_count=len(report['cases']),
                    checks=[check('no_forbidden_network_attempts',budget.blocked==0)])
                report=save_reports(output,report,[credential.get('key')])
            if compact:
                (output/'scenario-plan.json').write_text(json.dumps({'version':VERSION,'personas':PERSONAS,'scenarios':{k:SPECS[k] for k in CASES}},indent=2,default=encode)+'\n')
            if continuity:
                (output/'scenario-plan.json').write_text(json.dumps({'version':VERSION,'cases':{k:SPECS[k] for k in CASES}},indent=2)+'\n')
            if needs:
                from .needs_discovery import SPECS
                (output/'scenario-plan.json').write_text(json.dumps({'version':VERSION,'cases':{k:{'project_index':SPECS[k][0],'lead_messages':SPECS[k][1],'variant':SPECS[k][2]} for k in CASES}},indent=2)+'\n')
            (output/'catalog.json').write_text(json.dumps(manifest,indent=2,default=encode)+'\n')
    except Exception as exc:report.update(status='ERROR',**error_details(exc))
    finally:event.remove(Engine,'before_cursor_execute',only_local)
    report=sanitize(report,[credential.get('key')])
    (output/'summary.json').write_text(json.dumps(report,indent=2,default=encode)+'\n')
    bundle(output)
    return 0 if report.get('status') in {'PREPARED','PASS'} else 2


if __name__=='__main__':raise SystemExit(run(sys.argv[1],sys.argv[2]))
