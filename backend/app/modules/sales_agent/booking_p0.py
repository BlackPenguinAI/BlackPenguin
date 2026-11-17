"""P0: booking persistence diagnostics, without logging SQL, parameters or PII.

Safe to import in live traffic. This module does not perform database writes;
checked_flush simply preserves existing flush behaviour and annotates failures.
"""
import re
from sqlalchemy.exc import DBAPIError

BOOKING_PHASES = frozenset({'meeting_insert', 'booking_receipt_insert'})
_SQLSTATE = re.compile(r'^[A-Z0-9]{5}$')
_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,62}$')


def _identifier(value):
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def checked_flush(session, phase):
    """Flush unmodified, retaining a harmless phase label on a DBAPI failure.

    The caller is still responsible for rolling back the failed transaction.
    Never catch-and-continue after a PostgreSQL transaction has failed.
    """
    if phase not in BOOKING_PHASES:
        raise ValueError('Unsupported booking phase')
    try:
        session.flush()
    except DBAPIError as exc:
        exc._bp_booking_phase = phase
        raise


def structured_database_error(exc):
    """Return allowlisted PostgreSQL metadata only, never statement/params/messages.

    For psycopg2 and psycopg3; also safe with other DBAPI drivers.
    """
    if not isinstance(exc, DBAPIError):
        return None
    original = getattr(exc, 'orig', None)
    diag = getattr(original, 'diag', None)
    state = getattr(original, 'sqlstate', None) or getattr(original, 'pgcode', None)
    result = {'dbapi_error': type(exc).__name__}
    if isinstance(state, str) and _SQLSTATE.fullmatch(state.upper()):
        result['sqlstate'] = state.upper()
    for target, name in (
        ('schema', 'schema_name'),
        ('table', 'table_name'),
        ('column', 'column_name'),
        ('constraint', 'constraint_name'),
        ('datatype', 'datatype_name'),
    ):
        clean = _identifier(getattr(diag, name, None))
        if clean:
            result[target] = clean
    phase = getattr(exc, '_bp_booking_phase', None)
    if phase in BOOKING_PHASES:
        result['booking_phase'] = phase
    return result
