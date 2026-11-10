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
    if engine.dialect.name!='sqlite' or not engine.url.database or Path(engine.url.database).parent!=path.parent:
        raise PermissionError('Booking iteration requires its private SQLite database.')
    Base.metadata.create_all(engine)
    credential=options['credential'];budget=Budget(options['max_calls'])
    report={'version':'sales-booking-point/1.0','synthetic_only':True,'production_database_writes':0,
        'lead_contacts':0,'provider_calls':0,'lead_model':None,'judge_model':None,'commit':settings.APP_COMMIT_SHA,'cases':[],
        'limitations':['Google Calendar integration and transport delivery are not exercised.',
            'Simulation selects the first eligible seller, not the production round-robin cursor.',
            'SQLite does not verify PostgreSQL concurrent-booking locks.',
            'Public availability wording requires human review. No notification is scheduled.',
            'The six focused cases do not represent all eight buyer segments.']}
    def only_local(connection,*args):
        if connection.engine is not engine:raise PermissionError('Non-lab database access blocked.')
    event.listen(Engine,'before_cursor_execute',only_local)
    try:
        with SessionLocal() as db:
            with guard(Budget(0)):manifest=seed(db,output/'materials')
            report.update(company_name=manifest['company_name'],company_id=manifest['company_id'],project_count=3,property_count=6,
                project_name=manifest['projects'][0]['name'])
            if options['prepare_only']:
                report['team']=team(db,manifest,'all_projects',datetime.utcnow())
                report.update(status='PREPARED',model_quality_evaluated=False,scenario_count=6,scenarios=list(CASES))
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
                report.update(provider_calls=budget.calls,provider_usage=budget.usage,scenario_count=len(report['cases']),
                    checks=[check('no_forbidden_network_attempts',budget.blocked==0)])
                report=save_reports(output,report,[credential.get('key')])
            (output/'catalog.json').write_text(json.dumps(manifest,indent=2,default=encode)+'\n')
    except Exception as exc:report.update(status='ERROR',**error_details(exc))
    finally:event.remove(Engine,'before_cursor_execute',only_local)
    report=sanitize(report,[credential.get('key')])
    (output/'summary.json').write_text(json.dumps(report,indent=2,default=encode)+'\n')
    bundle(output)
    return 0 if report.get('status') in {'PREPARED','PASS'} else 2


if __name__=='__main__':raise SystemExit(run(sys.argv[1],sys.argv[2]))
