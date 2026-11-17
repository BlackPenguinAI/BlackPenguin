"""Read-only PostgreSQL preflight for the AI SDR first-booking path.

Usage: python -m tools.sales_ai.p0_booking_schema_probe [--conversation-id UUID]
No model/provider calls, messages, SQL mutations, lead details, or secrets.
"""
import argparse
import json
import re
from sqlalchemy import text

# Only literals that the deployed first-booking path actually writes.
EXPECTED_LITERALS = (
    ('meetings', 'status', 'CONFIRMED'),
    ('meetings', 'confirmation_status', 'confirmed'),
    ('meetings', 'modality', 'showroom'),
    ('meetings', 'calendar_sync_status', 'pending'),
    ('meetings', 'location_confirmation_status', 'confirmed'),
    ('meetings', 'location_confirmed_by', 'lead'),
    ('meetings', 'source', 'agent_next_first_booking'),
    ('leads', 'funnel_stage', 'APPOINTMENT_SET'),
    ('leads', 'pipeline_stage', 'S09_HANDOFF'),
    ('leads', 'agent_status', 'appointment_confirmed'),
    ('sales_conversations', 'stage', 'appointment_confirmed'),
    ('sales_booking_operations', 'calendar_status', 'pending'),
)

_COLUMN_SQL = text('''
SELECT table_name, column_name, data_type, udt_name, character_maximum_length
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name IN ('meetings', 'leads', 'sales_conversations', 'sales_booking_operations')
''')
_ENUM_SQL = text('''
SELECT t.typname, e.enumlabel
FROM pg_type t
JOIN pg_enum e ON e.enumtypid = t.oid
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = current_schema()
ORDER BY t.typname, e.enumsortorder
''')


def inspect_literals(columns, enums):
    """Pure function: reason about mock or actual information_schema output."""
    found = {(r['table_name'], r['column_name']): r for r in columns}
    findings = []
    for table, column, value in EXPECTED_LITERALS:
        item = found.get((table, column))
        if item is None:
            findings.append({'table': table, 'column': column, 'reason': 'missing_column'})
            continue
        max_length = item.get('character_maximum_length')
        if max_length is not None and len(value) > max_length:
            findings.append({'table': table, 'column': column, 'reason': 'literal_exceeds_varchar', 'actual_max': max_length, 'required_min': len(value)})
        if item.get('data_type') == 'USER-DEFINED':
            enum_name = item.get('udt_name')
            if enum_name in enums and value not in enums[enum_name]:
                findings.append({'table': table, 'column': column, 'reason': 'enum_literal_unavailable', 'enum_type': enum_name})
    return findings


def run(conversation_id=None):
    from app.db.postgres import engine
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('This read-only probe only supports PostgreSQL.')
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            columns = list(conn.execute(_COLUMN_SQL).mappings())
            enum_rows = list(conn.execute(_ENUM_SQL).mappings())
            enums = {}
            for row in enum_rows:
                enums.setdefault(row['typname'], set()).add(row['enumlabel'])
            issues = inspect_literals(columns, enums)
            report = {
                'status': 'PASS' if not issues else 'FAIL',
                'read_only': True,
                'checked_literals': len(EXPECTED_LITERALS),
                'findings': issues,
                'note': 'A PASS rules out these static schema mismatches; it does not identify a historical SQL exception.',
            }
            if conversation_id:
                row = conn.execute(text('''
                    SELECT count(*)
                    FROM meetings m
                    WHERE m.lead_id IN (
                        SELECT lead_id FROM sales_conversations WHERE id = :cid
                    )
                '''), {'cid': conversation_id}).scalar_one()
                receipts = conn.execute(text('''
                    SELECT count(*) FROM sales_booking_operations
                    WHERE conversation_id = :cid
                '''), {'cid': conversation_id}).scalar_one()
                report['conversation'] = {'meeting_count': row, 'booking_receipt_count': receipts}
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation-id', default=None)
    args = parser.parse_args()
    if args.conversation_id and not re.fullmatch(r'[0-9a-fA-F-]{36}', args.conversation_id):
        parser.error('conversation-id must be a UUID')
    try:
        report = run(args.conversation_id)
    except Exception as exc:
        # Do not echo a driver exception: its message may contain database data.
        report = {'status': 'ERROR', 'error_type': type(exc).__name__, 'read_only': True}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
