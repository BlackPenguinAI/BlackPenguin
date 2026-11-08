"""Project-scoped SELECT-only export. No leads, messages, tokens or Calendar calls.

Run from backend inside the API container, not from a browser console:
python -m tools.sales_ai.export_context --project-id UUID --output /tmp/sales-context.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .snapshot import (ASSET_FIELDS, ASSIGNMENT_FIELDS, BLOCK_FIELDS, SOURCE_FIELDS,
                       TYPE_FIELDS, UNIT_FIELDS, USER_FIELDS, WINDOW_FIELDS, build_catalog)


def export_project_context(engine, project_ids, *, now=None, days=30):
    from sqlalchemy import bindparam, inspect, text
    ids = list(dict.fromkeys(project_ids))
    if not ids:
        raise ValueError('At least one project ID is required.')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or not 1<=days<=90:
        raise ValueError('Use an aware capture time and a 1-90 day schedule window.')
    start=now.astimezone(timezone.utc).replace(tzinfo=None)
    end=start+timedelta(days=days)
    with engine.connect() as connection:
        if connection.dialect.name == 'postgresql':
            connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            connection.exec_driver_sql("SET LOCAL statement_timeout = '30000ms'")
            connection.exec_driver_sql("SET LOCAL lock_timeout = '2000ms'")
        elif connection.dialect.name == 'sqlite':
            connection.exec_driver_sql('PRAGMA query_only = ON')
        else:
            raise ValueError('Only PostgreSQL and isolated SQLite are supported.')
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        gaps = []

        def select(table, fields, scope_column, values, *, period=None):
            if table not in existing:
                gaps.append({'table': table, 'reason': 'missing_table'})
                return []
            available = {c['name'] for c in inspector.get_columns(table)}
            if scope_column not in available:
                raise ValueError('Required scope column is missing.')
            selected = [f for f in fields if f in available]
            missing = sorted(set(fields)-available)
            if missing:
                gaps.append({'table': table, 'reason': 'missing_columns', 'columns': missing})
            projection = ', '.join('"'+f+'"' for f in selected)
            if table == 'project_onboarding_sources' and 'storage_path' in available:
                projection += ", (storage_path IS NOT NULL AND storage_path <> '') AS has_stored_file"
            predicate='"'+scope_column+'" IN :ids'
            if period:
                if not set(period).issubset(available):raise ValueError('Schedule interval columns are missing.')
                predicate+=' AND "'+period[0]+'" < :end AND "'+period[1]+'" > :start'
            query = text('SELECT '+projection+' FROM "'+table+'" WHERE '+predicate).bindparams(bindparam('ids', expanding=True))
            result = [dict(r) for r in connection.execute(query, {'ids': list(values),'start':start,'end':end}).mappings()]
            for row in result:
                for field in ('profile_data','field_states','field_sources','published_snapshot','features','content_tags','allowed_channels','scopes'):
                    if isinstance(row.get(field),str):
                        row[field]=json.loads(row[field])
                if 'has_stored_file' in row:
                    row['has_stored_file'] = bool(row['has_stored_file'])
            return result

        rows = {}
        rows['projects'] = select('projects', 'id company_id name address city country timezone is_active is_demo onboarding_status'.split(), 'id', ids)
        if {p['id'] for p in rows['projects']} != set(ids):
            raise ValueError('A selected project does not exist.')
        companies = {p['company_id'] for p in rows['projects']}
        rows['companies'] = select('companies', ['id'], 'id', companies)
        specs = [
            ('project_profiles', 'id project_id profile_data field_states field_sources published_snapshot final_approved draft_revision updated_at approved_for_sales_at'.split()),
            ('project_property_types', TYPE_FIELDS), ('project_units', UNIT_FIELDS),
            ('project_sales_assets', ASSET_FIELDS),
            ('project_onboarding_sources', [f for f in SOURCE_FIELDS if f != 'has_stored_file']),
            ('project_user_assignments', ASSIGNMENT_FIELDS),
        ]
        for table, fields in specs:
            rows[table] = select(table, fields, 'project_id', ids)
        assigned_ids={a['user_id'] for a in rows['project_user_assignments']}
        rows['users'] = select('users', USER_FIELDS, 'id', assigned_ids)
        user_ids = {u['id'] for u in rows['users']}
        rows['sales_availability_windows'] = select('sales_availability_windows', WINDOW_FIELDS, 'user_id', user_ids)
        rows['sales_availability_blocks'] = select('sales_availability_blocks', BLOCK_FIELDS, 'user_id', user_ids,period=('starts_at','ends_at'))
        result = build_catalog({'generated_at': now.astimezone(timezone.utc).isoformat(), 'app_commit_sha': None}, rows, project_ids=ids)
        result['recorded_meeting_intervals']=[]
        if 'meetings' in existing:
            available={c['name'] for c in inspector.get_columns('meetings')}
            fields='assigned_sales_user_id meeting_time duration_minutes status confirmation_status calendar_sync_status'.split()
            if not set(fields).issubset(available):raise ValueError('Meeting interval columns are missing.')
            overlap="meeting_time + (COALESCE(duration_minutes,45) * INTERVAL '1 minute') > :start" if connection.dialect.name=='postgresql' else "datetime(meeting_time, '+' || COALESCE(duration_minutes,45) || ' minutes') > datetime(:start)"
            query=text('SELECT '+', '.join(fields)+' FROM meetings WHERE assigned_sales_user_id IN :ids AND meeting_time < :end AND '+overlap).bindparams(bindparam('ids',expanding=True))
            result['recorded_meeting_intervals']=[dict(r) for r in connection.execute(query,{'ids':sorted(user_ids),'start':start,'end':end}).mappings()]
        result['integration_status'] = {
            'company_messaging': select('telnyx_company_configurations', 'company_id primary_channel live_sms_enabled verification_status live_whatsapp_enabled whatsapp_verification_status regulatory_status updated_at'.split(), 'company_id', companies),
            'specialist_calendars': select('calendar_connections', 'user_id provider status scopes token_expires_at last_synced_at'.split(), 'user_id', user_ids),
            'meta': select('meta_connections', 'id company_id verification_status leads_access_confirmed scopes expires_at'.split(), 'company_id', companies),
            'live_probes_performed': False,
        }
        result['schema_gaps'] = gaps
        result['export_scope'] = {'project_ids': sorted(ids), 'database_read_only': True,
                                  'leads_exported': 0, 'messages_exported': 0, 'external_actions': 0,
                                  'schedule_start_utc':now.astimezone(timezone.utc).isoformat(),
                                  'schedule_end_utc':end.replace(tzinfo=timezone.utc).isoformat(),
                                  'meeting_interval_note':'Status determines whether an interval blocks time; no lead details or external Calendar events were exported.'}
        connection.rollback()
        return result


def serial(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--days',type=int,default=30)
    args = parser.parse_args()
    try:
        from app.core.config import settings
        from app.db.postgres import engine
        result = export_project_context(engine, args.project_id,days=args.days)
        result['source_commit'] = settings.APP_COMMIT_SHA
        # Exclusive creation prevents silently replacing a previous capture.
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False, default=serial)
            stream.write('\n')
    except Exception as error:
        # Driver exceptions may contain credentials or SQL parameters.
        parser.exit(1, 'Read-only export failed: '+type(error).__name__+'. No database writes performed.\n')
    print('Project context exported; external_actions=0; leads=0; messages=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
