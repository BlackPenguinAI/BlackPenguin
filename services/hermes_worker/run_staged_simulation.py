"""Standalone isolated Hermes SDK worker CLI, never used by the live queue.

The CLI reads a pre-existing persisted inbound simulation message. There is no
HTTP listener and no provider-dispatch capability. Run only on a private staging
DB or a deliberately authorized demo lead in a test environment.
"""
import argparse
import json
import os

from app.modules.hermes_sales_core.contracts import TurnScope
from app.modules.hermes_sales_core.staff_config import settings_for_turn
from app.modules.hermes_sales_core.p08_simulation import execute_staged_simulation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('company-id', 'project-id', 'conversation-id', 'lead-id', 'inbound-message-id'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    # Never point the staging CLI at an unvetted production database.
    if os.environ.get('ENVIRONMENT', '').lower() not in {'test', 'staging'}:
        raise SystemExit('P08 isolated simulation runner requires ENVIRONMENT=test or staging')
    # A mistyped ENVIRONMENT must not authorize writes to the real production DB.
    from sqlalchemy.engine.url import make_url
    from app.core.config import settings as core_settings
    database = (make_url(core_settings.DATABASE_URL).database or '').rsplit('/', 1)[-1].lower()
    if not any(term in database for term in ('staging', 'test')):
        raise SystemExit('P08 runner refuses a database not explicitly named staging/test')
    from app.db.postgres import SessionLocal
    db = SessionLocal()
    try:
        settings, version_id, tools = settings_for_turn(db)
        if version_id is None:
            raise SystemExit('No published Hermes version available')
        scope = TurnScope(args.company_id, args.project_id, args.conversation_id, args.lead_id)
        result = execute_staged_simulation(
            db, scope, inbound_message_id=args.inbound_message_id,
            settings=settings, enabled_tools=tools, published_version_id=version_id)
        # Deliberately no raw prompt, secrets, history or private tool data.
        print(json.dumps({k:v for k,v in result.items() if k!='reply'}, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
