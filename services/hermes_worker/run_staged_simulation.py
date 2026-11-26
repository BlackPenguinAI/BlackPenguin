"""HEI-01B isolated Hermes SDK runner; NEVER use a production database.

Accept an existing simulation inbound, or create one scoped test event from a
message file. Optional native demo effects; never real SMS/WhatsApp or Calendar.
"""
import argparse
import json
from pathlib import Path
import sys

from app.modules.hermes_sales_core.contracts import TurnScope
from app.modules.hermes_sales_core.staged_runtime import execute_isolated_turn, require_staging_database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('company-id', 'project-id', 'conversation-id', 'lead-id'):
        parser.add_argument('--' + name, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--inbound-message-id')
    group.add_argument('--event-id')
    parser.add_argument('--message-file', type=Path)
    parser.add_argument('--execute-native-effects', action='store_true',
                        help='Execute one authorized native demo effect after the staged turn.')
    args = parser.parse_args(argv)
    if bool(args.event_id) != bool(args.message_file):
        parser.error('--event-id and --message-file must be provided together')
    from app.db.postgres import SessionLocal
    from app.core.config import settings as core_settings
    # Load the same mapped ORM registry used by BP migrations; no DDL.
    import app.db.base  # noqa: F401
    db = SessionLocal()
    try:
        require_staging_database(db, environment=core_settings.ENVIRONMENT)
        message = None
        if args.message_file:
            with args.message_file.open('rb') as source:
                data = source.read(12001)
            if len(data) > 12000:
                raise ValueError('Buyer message exceeds 12000 bytes.')
            message = data.decode('utf-8')
        scope = TurnScope(args.company_id, args.project_id, args.conversation_id, args.lead_id)
        result = execute_isolated_turn(db, scope,
            inbound_message_id=args.inbound_message_id, event_id=args.event_id, message=message)
        # Never emit model reply, prompt, credentials, tool arguments or history.
        fields = ('message_id', 'inbound_message_id', 'run_id', 'event_id', 'engine',
                  'engine_version', 'replayed', 'delivery', 'published_version_id', 'state_revision')
        output = {key: result[key] for key in fields if key in result}
        if args.execute_native_effects:
            from app.modules.hermes_sales_core.native_effects import execute_native_effect
            output['native_effect'] = execute_native_effect(
                db, scope, inbound_message_id=result['inbound_message_id'])
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception as exc:
        db.rollback()
        # Exceptions from a provider may include payloads/credentials. Only
        # report the class here; detailed inspection stays in the isolated DB.
        print('Isolated Hermes execution failed: ' + type(exc).__name__, file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
