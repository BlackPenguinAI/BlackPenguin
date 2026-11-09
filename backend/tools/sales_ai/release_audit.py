"""Project-scoped SELECT-only deployment/rollback inventory. No provider calls.

Run separately in API and worker environments. This observes configured process
identity and database state; it does not prove a worker loop is healthy or that
a provider actually delivered a message. It never changes a proposal or a flag.
"""
import argparse,hashlib,json,os,re
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from sqlalchemy import MetaData,Table,select,func,inspect,text,or_


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def canonical(value):
    if str(UUID(value))!=value:raise ValueError('Use canonical Company/Project UUIDs')
    return value


def audit(engine,company_id,project_id,*,commit='unknown',service='api',after_state_id=None,flags=None):
    canonical(company_id);canonical(project_id)
    if after_state_id:canonical(after_state_id)
    if service not in {'api','worker'}:raise ValueError('Select api or worker')
    if commit!='unknown' and not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Use a full commit SHA')
    required={'projects','ai_configurations','prompt_versions','sales_conversations','sales_dialogue_states','meetings',
        'sales_booking_operations','sales_reschedule_operations','sales_cancellation_operations','sales_wait_requests',
        'sales_moderation_incidents','sales_inbound_jobs','sales_follow_up_jobs','outbound_messages','notification_outbox'}
    with engine.connect() as connection:
        sqlite_before=None
        try:
            if connection.dialect.name=='postgresql':
                connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                connection.exec_driver_sql("SET LOCAL statement_timeout = '15000ms'")
                connection.exec_driver_sql("SET LOCAL lock_timeout = '2000ms'")
            elif connection.dialect.name=='sqlite':
                sqlite_before=connection.exec_driver_sql('PRAGMA query_only').scalar_one()
                connection.exec_driver_sql('PRAGMA query_only=ON')
            else:raise ValueError('Only PostgreSQL and isolated SQLite are supported')
            existing=set(inspect(connection).get_table_names());missing=sorted(required-existing)
            report={'version':'sales-release-audit/1.0','captured_at':datetime.now(timezone.utc).isoformat(),'service':service,'commit':commit,
                'scope':{'company_id':company_id,'project_id':project_id},'database_writes':0,'provider_calls':0,'acceptance_proven':False}
            if missing:return {**report,'status':'INCOMPATIBLE_SCHEMA','missing_tables':missing}
            meta=MetaData()
            def table(name):return Table(name,meta,autoload_with=connection) if name not in meta.tables else meta.tables[name]
            project=table('projects')
            if not connection.execute(select(project.c.id).where(project.c.id==project_id,project.c.company_id==company_id)).first():raise PermissionError('Project is outside the selected Company')
            config=table('ai_configurations');version=table('prompt_versions');selected_config=None
            for owner in [company_id,None]:
                configs=connection.execute(select(config.c.id,config.c.agent_ventas).where(config.c.company_id==owner)).mappings().all()
                versions=connection.execute(select(version.c.id,version.c.version_number,version.c.configuration).where(version.c.company_id==owner,version.c.agent_key=='sales',version.c.is_published.is_(True))).mappings().all()
                if len(configs)>1 or len(versions)>1:raise ValueError('Ambiguous Sales configuration/publication')
                if not configs or owner is not None and not versions:continue
                source=configs[0];published=versions[0] if versions else None;pack=published['configuration'] if published else source['agent_ventas']
                if not isinstance(pack,dict):raise ValueError('Invalid Sales configuration')
                runtime=pack.get('runtime_config') or {}
                selected_config={'configuration_id':source['id'],'version_id':published['id'] if published else None,'version_number':published['version_number'] if published else None,
                    'version_source':'published_snapshot' if published else 'legacy_active_config','configuration_sha256':digest(pack),'model':str(pack.get('model') or '')[:100],
                    'draft_differs_from_published':bool(published and digest(pack)!=digest(source['agent_ventas'])),
                    'runtime':{'mode':runtime.get('mode','disabled'),'scope':runtime.get('scope','cohort'),'lead_filter_count':len(runtime.get('lead_ids') or [])}}
                break
            counts={}
            for name,column in [('sales_booking_operations','calendar_status'),('sales_reschedule_operations','calendar_status'),('sales_cancellation_operations','calendar_status'),('sales_wait_requests','status'),('sales_moderation_incidents','disposition'),('notification_outbox','status')]:
                t=table(name);query=select(t.c[column],func.count()).where(t.c.company_id==company_id,t.c.project_id==project_id).group_by(t.c[column])
                counts[name]={str(status):number for status,number in connection.execute(query)}
            meetings=table('meetings');counts['meetings']={str(status).lower():n for status,n in connection.execute(select(meetings.c.status,func.count()).where(meetings.c.project_id==project_id).group_by(meetings.c.status))}
            conversations=table('sales_conversations');conversation_ids=select(conversations.c.id).where(conversations.c.company_id==company_id,conversations.c.project_id==project_id)
            for name in ['sales_inbound_jobs','sales_follow_up_jobs','outbound_messages']:
                t=table(name);counts[name]={str(status):n for status,n in connection.execute(select(t.c.status,func.count()).where(t.c.conversation_id.in_(conversation_ids)).group_by(t.c.status))}
            states=table('sales_dialogue_states');query=select(states.c.id,states.c.conversation_id,states.c.revision,states.c.state_json).where(states.c.company_id==company_id,states.c.project_id==project_id)
            if after_state_id:query=query.where(states.c.id>after_state_id)
            rows=connection.execute(query.order_by(states.c.id).limit(101)).mappings().all();pending=[]
            for row in rows[:100]:
                state=row['state_json'] or {}
                if not isinstance(state,dict):raise ValueError('Invalid dialogue state; preserve it for review')
                kinds=[key for key in ['booking_proposal','reschedule_proposal','cancellation_proposal'] if state.get(key)]
                if state.get('wait_context'):kinds.append('wait_context')
                if kinds:pending.append({'state_id':row['id'],'conversation_id':row['conversation_id'],'revision':row['revision'],'state_sha256':digest(state),'contexts':kinds})
            heads=[]
            if 'alembic_version' in existing:
                t=table('alembic_version');heads=list(connection.execute(select(t.c.version_num)).scalars())
            return {**report,'status':'INSPECTED_NOT_ACCEPTED','migration_heads':heads,'configuration':selected_config,'flags':flags or {},'counts':counts,
                'pending_context_page':pending,'states_scanned':min(len(rows),100),'next_state_id':rows[99]['id'] if len(rows)>100 else None,
                'scope_limits':'Counts use stored source project IDs; audit every source and target project for cross-project operations. Pending contexts are paginated, not an exhaustive single-page drain report.',
                'sensitive_values_exported':False,'worker_loop_health_proven':False}
        finally:
            connection.rollback()
            if sqlite_before is not None:connection.exec_driver_sql('PRAGMA query_only='+str(int(sqlite_before)))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--company-id',required=True);parser.add_argument('--project-id',required=True);parser.add_argument('--service',choices=['api','worker'],required=True);parser.add_argument('--after-state-id');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    if not os.environ.get('DATABASE_URL'):
        report={'version':'sales-release-audit/1.0','status':'BLOCKED','reason':'DATABASE_URL_MISSING','database_writes':0,'provider_calls':0,'acceptance_proven':False}
    else:
        engine=None
        try:
            from sqlalchemy import create_engine
            from app.core.config import settings
            from app.modules.sales_agent.next_flow import selected
            engine=create_engine(settings.DATABASE_URL)
            flags={'dialogue_runtime_enabled':settings.SALES_DIALOGUE_RUNTIME_ENABLED,'new_flow_project_selected':selected(SimpleNamespace(project_id=args.project_id))}
            report=audit(engine,args.company_id,args.project_id,commit=settings.APP_COMMIT_SHA,service=args.service,after_state_id=args.after_state_id,flags=flags)
        except Exception as exc:report={'version':'sales-release-audit/1.0','status':'AUDIT_FAILED','error_code':type(exc).__name__,'database_writes':0,'provider_calls':0,'acceptance_proven':False}
        finally:
            if engine is not None:engine.dispose()
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(report['status']);return 0 if report['status']=='INSPECTED_NOT_ACCEPTED' else 2


if __name__=='__main__':raise SystemExit(main())
