"""Private SQLite lab worker. All commercial state and material writes are disposable."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

from .evaluation_checks import check, error_details, sanitize
from .evaluation_guard import Budget, guard
from .evaluation_worker import evaluate, save_reports
from .synthetic_fixtures import COMPANY_NAME, VERSION, seed


def personas(project):
    props=project['properties'];first=props[0];material=props[-1] if project['key']=='cedar' else first
    focus=props[1] if project['key']=='sierra' else first
    common={'project':project['name'],'buying_purpose':'primary residence',
            'budget_currency':'USD','budget_amount':900000,'payment':'cash',
            'boundaries':'Do not book, pay, give a real phone number, or consent to external contact.'}
    return {
        'new_buyer':{**common,'goals':['Ask which property types are available and their prices.',
            'Ask about bedrooms and area of '+first['name']+'.',
            'Disclose your budget and cash payment if asked; do not repeat already answered questions.']},
        'targeted_materials':{**common,'property_interest':material['name'],
            'goals':['Ask for photos and a PDF brochure specifically for '+material['name']+'.',
                'Accept an offered exact requested resource; if unavailable accept the answer without requesting substitutes.',
                'Ask whether parking is confirmed for this property. Do not switch properties.']},
        'continuity':{**common,'property_interest':focus['name'],
            'goals':['Ask price and current availability of '+focus['name']+'.',
                'Explain you have cash; if misunderstood correct the misunderstanding naturally.',
                'Then explicitly change payment preference to bank financing and ask about bedrooms in the SAME message.',
                'Do not accept a substitute property unless you explicitly choose it.']},
    }


def material_checks(db, project, cases):
    """Verify real sandbox shares, not the model's claim that it sent something."""
    from app.modules.sales_agent.models import AgentRun, SalesConversation
    from app.modules.projects.models import ProjectSalesAsset, SalesAssetShare
    for case in cases:
        runs=[db.get(AgentRun,t['run_id']) for t in case['turns'] if t.get('run_id')]
        conversations={run.conversation_id for run in runs}
        leads={db.get(SalesConversation,c).lead_id for c in conversations}
        shares=db.query(SalesAssetShare).filter(SalesAssetShare.lead_id.in_(leads)).all() if leads else []
        assets=[db.get(ProjectSalesAsset,s.sales_asset_id) for s in shares]
        case['checks'].append(check('shared_resources_belong_to_active_project',all(a and a.project_id==project['id'] for a in assets)))
        understandings=[t.get('understanding') or {} for t in case['turns']]
        requests=[r for u in understandings for r in u.get('requests',[])]
        topics={r.get('topic') for r in requests}
        if case['case']=='new_buyer':
            case['checks'].append(check('inventory_goal_exercised',bool(topics & {'inventory','catalog'})))
            case['checks'].append(check('property_detail_goal_exercised','property_details' in topics))
        if case['case']=='continuity':
            preferences=[p for u in understandings for p in u.get('preferences',[]) if p.get('key')=='financing']
            case['checks'].append(check('payment_change_goal_exercised',len(preferences)>=2))
            case['checks'].append(check('mixed_payment_and_question_goal_exercised',any(
                any(p.get('key')=='financing' for p in u.get('preferences',[])) and
                any(r.get('topic')=='property_details' for r in u.get('requests',[])) for u in understandings)))
        if case['case']=='targeted_materials':
            item=project['properties'][-1] if project['key']=='cedar' else project['properties'][0]
            wanted={r['asset_id'] for r in item['resources']}
            actual={s.sales_asset_id for s in shares}
            # Persona explicitly rejects substitutes; an offer is not delivery.
            case['checks'].append(check('no_unrequested_property_resource',actual<=wanted))
            case['checks'].append(check('available_requested_resources_shared',wanted<=actual))
            topics=[r for t in case['turns'] for r in (t.get('understanding') or {}).get('requests',[])]
            case['checks'].append(check('material_goal_exercised',any(r.get('topic')=='materials' for r in topics)))


def bundle(output):
    destination=output/'synthetic-sales-results.zip'
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path!=destination:archive.write(path,path.relative_to(output))


def run(options_path, output):
    import app.db.base
    from app.db.postgres import engine,SessionLocal
    from app.core.config import settings
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from app.modules.ai_core.models import AIConfiguration,PromptVersion
    from .evaluation import encode
    from .synthetic_fixtures import identifier
    options_path=Path(options_path);output=Path(output);options=json.loads(options_path.read_text())
    if (engine.dialect.name!='sqlite' or not engine.url.database or
            Path(engine.url.database).parent!=options_path.parent):
        raise PermissionError('Lab requires its private SQLite database.')
    credential=options['credential'];secrets=[credential.get('key')]
    summary={'version':VERSION,'company_name':COMPANY_NAME,'synthetic_only':True,'status':'ERROR',
        'production_database_writes':0,'lead_contacts':0,'project_count':0,'property_count':0,
        'scenario_count':0,'provider_calls':0,'projects':[],'commit':settings.APP_COMMIT_SHA,
        'limitations':['Calendar booking and transport delivery are not tested.',
            'A lead LLM is not an independent quality oracle; inspect traces and deterministic checks.',
            'Illustrations are synthetic fixtures, not architectural renderings or real property photos.']}
    from app.db.postgres import Base
    Base.metadata.create_all(engine)
    budget=Budget(options['max_calls'])
    def only_local(connection,*args):
        if connection.engine is not engine:raise PermissionError('Non-lab database access blocked.')
    event.listen(Engine,'before_cursor_execute',only_local)
    try:
        with SessionLocal() as db:
            with guard(Budget(0)):
                manifest=seed(db,output/'materials')
            (output/'catalog.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
            summary.update(company_id=manifest['company_id'],project_count=len(manifest['projects']),
                property_count=sum(len(p['properties']) for p in manifest['projects']))
            if options['prepare_only']:
                summary['status']='PREPARED';summary['model_quality_evaluated']=False
            else:
                db.add(AIConfiguration(id=credential['id'],company_id=None,openrouter_api_key=credential['key'],agent_ventas=credential['pack']))
                db.add(PromptVersion(id=credential['version_id'],company_id=None,agent_key='sales',
                    version_number=credential['version_number'],is_published=True,configuration=credential['pack'],
                    published_at=datetime.fromisoformat(credential['published_at']) if isinstance(credential['published_at'],str) else credential['published_at']))
                db.commit()
                summary['quality_scope']='Automated contract, goal-coverage and resource checks; not a proof of conversational quality.'
                summary['lead_model']=options.get('lead_model') or credential['pack']['model']
                summary['sales_model']=credential['pack']['model']
                summary['configuration_version']=credential['version_number']
                totals={'PASS':0,'FAIL':0,'BLOCKED':0};projects=manifest['projects']
                for index,project in enumerate(projects):
                    remaining=options['max_calls']-budget.calls
                    allocation=remaining//(len(projects)-index)
                    if allocation<=0:
                        summary['projects'].append({'project':project['name'],'status':'INCOMPLETE','reason':'global_call_budget_exhausted'})
                        totals['BLOCKED']+=1;continue
                    budget.maximum=budget.calls+allocation
                    before_calls=budget.calls;before_usage=dict(budget.usage)
                    opt={'mode':'adaptive','max_turns':options['max_turns'],'judge':options['judge'],
                         'personas':personas(project),'lead_model':options.get('lead_model')}
                    report={'version':VERSION,'mode':'synthetic_adaptive','project_name':project['name'],
                        'project_id':project['id'],'approved_revision':project['approved_revision'],
                        'synthetic_only':True,'production_database_writes':0,'lead_contacts':0,'commit':settings.APP_COMMIT_SHA,
                        'material_errors':[],'options':opt,'cases':[]}
                    try:
                        with guard(budget),patch('app.integrations.openrouter_client.record_openrouter_usage',lambda **kw:None):
                            cases,_,guidance=asyncio.run(evaluate(db,{**project,'project_id':project['id'],'company_id':manifest['company_id'],'tables':{},'material_errors':[]},opt,budget))
                        report.update(cases=cases,**guidance)
                        material_checks(db,project,cases)
                    except Exception as exc:
                        db.rollback();report.update(error_details(exc))
                    report.update(provider_calls=budget.calls-before_calls,
                        provider_usage={k:budget.usage[k]-before_usage[k] for k in budget.usage},
                        blocked_network_calls=budget.blocked,
                        checks=[check('no_forbidden_network_attempts',budget.blocked==0)])
                    result=save_reports(output/project['key'],report,secrets)
                    summary['projects'].append({'project':project['name'],'status':result['status'],
                        'summary':result['summary'],'report':project['key']+'/report.json','provider_calls':report['provider_calls'],'budget_exhausted':budget.calls>=budget.maximum})
                    summary['scenario_count']+=len(report['cases'])
                    for status,value in result['summary'].items():totals[status]+=value
                summary.update(summary=totals,provider_calls=budget.calls,provider_usage=budget.usage,
                    blocked_network_calls=budget.blocked)
                statuses={p['status'] for p in summary['projects']}
                summary['status']='ERROR' if 'ERROR' in statuses else 'FAIL' if 'FAIL' in statuses else 'INCOMPLETE' if statuses-{'PASS'} else 'PASS'
    except Exception as exc:
        summary.update(error_details(exc))
    finally:
        event.remove(Engine,'before_cursor_execute',only_local)
    summary=sanitize(summary,secrets)
    output.mkdir(parents=True,exist_ok=True)
    (output/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=encode)+'\n')
    bundle(output)
    return 0 if summary['status'] in {'PREPARED','PASS'} else 2


if __name__=='__main__':raise SystemExit(run(sys.argv[1],sys.argv[2]))
