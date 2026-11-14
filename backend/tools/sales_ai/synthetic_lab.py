"""Create three synthetic projects; optionally run isolated LLM-lead dialogues."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from .evaluation import child_environment, encode


def configuration(source_engine, config_id):
    """Only global published Sales configuration/credential; no tenant/lead reads."""
    from sqlalchemy import select, text
    import app.db.base
    from app.db.postgres import Base
    tables=Base.metadata.tables
    with source_engine.connect() as connection, connection.begin():
        if connection.dialect.name=='postgresql':
            connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
        elif connection.dialect.name!='sqlite':raise ValueError('Unsupported configuration source.')
        t=tables['ai_configurations'];query=select(t).where(t.c.company_id.is_(None))
        if config_id:query=query.where(t.c.id==config_id)
        rows=list(connection.execute(query).mappings())
        if len(rows)!=1:raise ValueError('Select one global Sales configuration.')
        row=rows[0];t=tables['prompt_versions']
        versions=list(connection.execute(select(t).where(t.c.company_id.is_(None),t.c.agent_key=='sales',t.c.is_published.is_(True))).mappings())
        if len(versions)!=1:raise ValueError('Exactly one published global Sales version is required.')
        version=versions[0]
        if not row['openrouter_api_key'] or not version['configuration'].get('model'):
            raise ValueError('Published model and credential are required.')
        return {'id':row['id'],'key':row['openrouter_api_key'],'pack':version['configuration'],
            'version_id':version['id'],'version_number':version['version_number'],'published_at':version['published_at']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true',help='No database reads or model calls.')
    parser.add_argument('--configuration-id')
    parser.add_argument('--suite',choices=['adaptive','booking-point','commercial-point','closing-point','compact-battery','needs-discovery','continuity-battery'],default='adaptive')
    parser.add_argument('--cases',nargs='+',help='Case IDs for compact, needs or continuity suites; omitted runs the suite defaults.')
    parser.add_argument('--lead-model',help='Optional OpenRouter model for the synthetic buyer; sales model stays published.')
    parser.add_argument('--max-calls',type=int,default=180,help='Global inference-call cap, not a currency cap.')
    parser.add_argument('--max-turns',type=int,default=6)
    parser.add_argument('--judge',action='store_true',help='Optional advisory LLM judge; also consumes call budget.')
    args=parser.parse_args()
    if args.suite in {'booking-point','commercial-point','closing-point','compact-battery','needs-discovery','continuity-battery'} and (args.judge or args.lead_model):parser.error('Focused suites use scripted leads and no judge.')
    if args.cases and args.suite not in {'compact-battery','needs-discovery','continuity-battery'}:parser.error('--cases is available only for compact-battery, needs-discovery and continuity-battery.')
    if args.suite=='continuity-battery':
        from .continuity_battery import CASES
        if args.cases and (len(set(args.cases))!=len(args.cases) or set(args.cases)-set(CASES)):parser.error('Invalid continuity cases.')
        if args.max_turns<6:parser.error('Continuity requires at least six turns.')
    if args.suite=='needs-discovery':
        from .needs_discovery import CASES
        if args.cases and (len(set(args.cases))!=len(args.cases) or set(args.cases)-set(CASES)):parser.error('Invalid needs-discovery cases.')
        if args.max_calls<2*len(args.cases or CASES):parser.error('Needs-discovery requires at least two calls per selected case.')
    if args.suite=='compact-battery':
        from .compact_battery import CASES
        if args.cases and (len(set(args.cases))!=len(args.cases) or set(args.cases)-set(CASES)):
            parser.error('Use distinct compact case IDs: '+', '.join(CASES))
        if args.max_calls<len(args.cases or CASES) or not 6<=args.max_turns<=8:
            parser.error('Compact-battery requires at least one call per selected case and 6..8 turns.')
    if args.suite=='booking-point' and (args.max_calls<6 or args.max_turns<4):parser.error('Booking-point requires at least 6 calls and 4 turns.')
    if args.suite=='commercial-point' and args.max_calls<8:parser.error('Commercial-point requires at least 8 calls.')
    if args.suite=='closing-point' and (args.max_calls<8 or args.max_turns<4):parser.error('Closing-point requires at least 8 calls and 4 turns.')
    if not 1<=args.max_calls<=600 or not 3<=args.max_turns<=20:parser.error('Use 1..600 calls and 3..20 turns.')
    args.output.mkdir(parents=True,exist_ok=True,mode=0o700)
    if any(args.output.iterdir()):parser.error('Use a new empty output directory.')
    output=args.output.resolve()
    with tempfile.TemporaryDirectory(prefix='bp-synthetic-sales-') as temporary:
        credential={}
        if not args.prepare_only:
            from app.db.postgres import engine
            credential=configuration(engine,args.configuration_id)
        data={'suite':args.suite,'case_selection':args.cases,'credential':credential,'prepare_only':args.prepare_only,'lead_model':args.lead_model,
              'max_calls':args.max_calls,'max_turns':args.max_turns,'judge':args.judge}
        path=Path(temporary)/'lab-options.json';path.write_text(json.dumps(data,default=encode));path.chmod(0o600)
        env=child_environment(temporary)
        completed=subprocess.run([sys.executable,'-m',('tools.sales_ai.booking_pilot_worker' if args.suite in {'booking-point','commercial-point','closing-point','compact-battery','needs-discovery','continuity-battery'} else 'tools.sales_ai.synthetic_lab_worker'),str(path),str(output)],
            cwd=temporary,env=env,timeout=1800,stderr=subprocess.PIPE,text=True)
        summary=output/'summary.json'
        if summary.is_file():
            result=json.loads(summary.read_text())
            print(json.dumps({k:result.get(k) for k in ('status','company_name','project_count','property_count','scenario_count','provider_calls','is_full_battery','expected_bookings','actual_bookings','summary')},indent=2))
            print('Bundle:',str(output/'synthetic-sales-results.zip'))
        else:print(json.dumps({'status':'ERROR','detail':'Worker failed before producing a summary. No raw stderr exposed.'}))
        return completed.returncode if summary.is_file() else 2


if __name__=='__main__':raise SystemExit(main())
