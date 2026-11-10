"""Evaluate the current Sales engine in a separate disposable process.

Production reads are transactionally read-only. No original leads are copied.
Run reports intentionally omit credentials and complete model request bodies.
"""
import argparse
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

VERSION = 'sales-engine-evaluation/1.0'


def encode(value):
    if isinstance(value, Enum): return value.name
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    raise TypeError(type(value).__name__)


def snapshot(source_engine, company_id, project_id, temporary):
    from sqlalchemy import select, or_, text
    import app.db.base
    from app.db.postgres import Base
    from app.core.config import settings
    tables = Base.metadata.tables
    result = {'tables': {}, 'material_errors': [], 'company_id': company_id, 'project_id': project_id}
    with source_engine.connect() as connection:
        with connection.begin():
            if connection.dialect.name == 'postgresql':
                connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            elif connection.dialect.name != 'sqlite':
                raise ValueError('Unsupported snapshot database.')
            def rows(name, predicate):
                return [dict(row) for row in connection.execute(select(tables[name]).where(predicate)).mappings()]
            project = rows('projects', (tables['projects'].c.id == project_id) & (tables['projects'].c.company_id == company_id))
            if len(project) != 1: raise ValueError('Project does not belong to the requested Company.')
            profiles = rows('project_profiles', tables['project_profiles'].c.project_id == project_id)
            if len(profiles) != 1: raise ValueError('Project has no profile.')
            profile = profiles[0]
            published = profile.get('published_snapshot')
            if not (isinstance(published, dict) and published.get('profile_id') == profile['id']
                    and published.get('company_id') == company_id and isinstance(published.get('states'), dict)):
                raise ValueError('An approved published Project snapshot is required.')
            result['project_name'] = project[0]['name']
            result['approved_revision'] = published.get('revision')
            result['approved_sha256'] = hashlib.sha256(json.dumps(published, sort_keys=True, default=encode).encode()).hexdigest()
            # Avoid copying Company billing/contact information or real user records.
            company = rows('companies', tables['companies'].c.id == company_id)[0]
            result['tables']['companies'] = [{k:company[k] for k in
                ('id','name','country_code','timezone','is_active')}]
            public = {'official_company_name','preferred_display_name','value_proposition','key_differentiators',
                'tone_of_voice','key_messaging','corporate_value_proposition','corporate_differentiators',
                'corporate_compliance_information'}
            company_profiles = rows('company_profiles', tables['company_profiles'].c.company_id == company_id)
            for row in company_profiles:
                for key in ('profile_data','field_states','field_sources'):
                    row[key] = {k:v for k,v in (row.get(key) or {}).items() if k in public}
                value = row.get('published_snapshot')
                if isinstance(value,dict):
                    row['published_snapshot'] = {k:v for k,v in value.items()
                        if k in {'profile_id','company_id','revision','legacy_capture'}}
                    row['published_snapshot'].update({key:{k:v for k,v in (value.get(key) or {}).items() if k in public}
                                                       for key in ('data','states','sources')})
                for col in list(row):
                    if col not in public and col not in {'id','company_id','profile_data','field_states','field_sources',
                            'final_approved','published_snapshot','draft_revision','completion_percentage'}:
                        row.pop(col)
            result['tables']['company_profiles'] = company_profiles
            result['tables']['projects'] = project
            result['tables']['project_profiles'] = profiles
            for name in ('project_property_types','project_units'):
                result['tables'][name] = rows(name, tables[name].c.project_id == project_id)
            a = tables['project_sales_assets']
            assets = rows(a.name, (a.c.project_id == project_id) & (a.c.company_id == company_id)
                          & a.c.approval_status.in_(['approved','approved_targeted']))
            result['tables'][a.name] = assets
            s = tables['project_onboarding_sources']
            sources = rows(s.name, (s.c.project_id == project_id) & s.c.id.in_([a['source_id'] for a in assets]))
            uploads = Path(temporary) / 'uploads'; uploads.mkdir(mode=0o700)
            total = 0
            root = Path(settings.PROJECT_UPLOAD_ROOT).expanduser().resolve()
            prefix = Path('companies') / company_id / 'projects' / project_id
            for row in sources:
                if not row.get('storage_path'): continue
                try:
                    path = (root / row['storage_path']).resolve()
                    if not path.is_relative_to(root / prefix): raise ValueError('Material outside project storage.')
                    if not path.is_file() or path.stat().st_size > 70 * 1024 * 1024: raise ValueError('Material too large or absent.')
                    content = path.read_bytes()
                    if row.get('is_encrypted'):
                        from app.modules.projects.storage_service import _fernet
                        content = _fernet().decrypt(content)
                    total += len(content)
                    if total > 100 * 1024 * 1024: raise ValueError('Material snapshot exceeds 100 MB.')
                    relative = str(prefix / 'evaluation' / (row['id'] + '.bin'))
                    destination = uploads / relative; destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content); destination.chmod(0o600)
                    row.update(storage_path=relative, is_encrypted=False)
                except Exception as exc:
                    result['material_errors'].append({'source_id': row['id'], 'error_code': type(exc).__name__})
                    row['storage_path'] = None
            result['tables'][s.name] = sources
            configs = rows('ai_configurations', or_(tables['ai_configurations'].c.company_id == company_id,
                                                    tables['ai_configurations'].c.company_id.is_(None)))
            result['tables']['ai_configurations'] = [{k: row[k] for k in
                ('id','company_id','openrouter_api_key','agent_ventas')} for row in configs]
            v = tables['prompt_versions']
            versions = rows(v.name, (v.c.agent_key == 'sales') & v.c.is_published.is_(True)
                            & or_(v.c.company_id == company_id, v.c.company_id.is_(None)))
            result['tables'][v.name] = versions
            for name in ('agent_operating_policies','knowledge_guidance_items'):
                if name not in tables: continue
                t = tables[name]; predicate = or_(t.c.company_id == company_id, t.c.company_id.is_(None))
                if 'project_id' in t.c: predicate &= or_(t.c.project_id == project_id, t.c.project_id.is_(None))
                result['tables'][name] = rows(name, predicate)
    return result


def child_environment(temporary):
    env = {k: v for k, v in os.environ.items() if k in ('PATH','PYTHONPATH','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR')}
    env.update(ENVIRONMENT='test', DATABASE_URL='sqlite:///' + str(Path(temporary) / 'evaluation.db'),
        SECRET_KEY='isolated-evaluation-only', ACCESS_TOKEN_EXPIRE_MINUTES='60',
        FIRST_SUPERADMIN_EMAIL='evaluation@example.invalid', FIRST_SUPERADMIN_PASSWORD='evaluation-only',
        META_ACCESS_TOKEN='not-configured', OPENROUTER_API_KEY='not-configured', SEED_MINTO_DEMO='false',
        PROJECT_UPLOAD_ROOT=str(Path(temporary) / 'uploads'), PUBLIC_APP_URL='https://evaluation.invalid',
        APP_COMMIT_SHA=os.environ.get('APP_COMMIT_SHA','unknown'))
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['replay','adaptive'], default='replay')
    parser.add_argument('--max-calls', type=int, default=80)
    parser.add_argument('--max-turns', type=int, default=8)
    parser.add_argument('--no-judge', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 200 or not 1 <= args.max_turns <= 20:
        parser.error('Require 1..200 calls and 1..20 turns per case.')
    from app.db.postgres import engine
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(args.output.iterdir()): parser.error('Use a new empty output directory.')
    with tempfile.TemporaryDirectory(prefix='bp-sales-evaluation-') as temporary:
        data = snapshot(engine, args.company_id, args.project_id, temporary)
        path = Path(temporary) / 'snapshot.json'
        path.write_text(json.dumps(data, default=encode)); path.chmod(0o600)
        options = {'mode':args.mode,'max_calls':args.max_calls,'max_turns':args.max_turns,'judge':not args.no_judge}
        options_path = Path(temporary) / 'options.json'; options_path.write_text(json.dumps(options))
        completed = subprocess.run([sys.executable,'-m','tools.sales_ai.evaluation_worker',str(path),
                                    str(options_path),str(args.output.resolve())],
                                   env=child_environment(temporary), timeout=1800,
                                   cwd=temporary,
                                   stderr=subprocess.PIPE, text=True)
        report_path = args.output / 'report.json'
        if not report_path.is_file():
            print(json.dumps({'status':'ERROR','worker_exit_code':completed.returncode,
                              'detail':'Worker failed before producing a report; no raw stderr exposed.'}))
            return 2
        report = json.loads(report_path.read_text())
        print(json.dumps({k:report.get(k) for k in ('status','mode','summary','judge_summary','provider_calls','project_name','approved_revision')},indent=2))
        print('Reports:', str(args.output.resolve()))
        return completed.returncode


if __name__ == '__main__':
    raise SystemExit(main())
