"""Bound Sales lock waits without committing caller-owned business effects.

Limits are transaction-local and reapplied after each commit/rollback. Other
application sessions keep their normal PostgreSQL settings.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session


def _limits(connection):
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql("SET LOCAL lock_timeout = '2s'")
        connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout = '120s'")


@event.listens_for(Session, 'after_begin')
def _after_begin(session, transaction, connection):
    if session.info.get('bounded_sales_transactions'):
        _limits(connection)


def bounded(db):
    """Opt a private Sales session into bounded PostgreSQL transactions."""
    db.info['bounded_sales_transactions'] = True
    if db.in_transaction():
        _limits(db.connection())
    return db
