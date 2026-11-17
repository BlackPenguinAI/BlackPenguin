"""Synthetic, offline P0 regression tests; no database or model calls."""
from types import SimpleNamespace
import pytest
from sqlalchemy.exc import DataError, IntegrityError
from app.modules.sales_agent.booking_p0 import checked_flush, structured_database_error
from tools.sales_ai.p0_booking_schema_probe import inspect_literals, EXPECTED_LITERALS


class FakeDriverError(Exception):
    def __init__(self, message, *, state='22001', diag=None):
        super().__init__(message)
        self.sqlstate = state
        self.diag = diag


class FakeSession:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def flush(self):
        self.calls += 1
        if self.error:
            raise self.error


def synthetic_error(kind=DataError, state='22001'):
    original = FakeDriverError(
        'TOP SECRET LEAD PHONE +1 555 999 5555', state=state,
        diag=SimpleNamespace(
            table_name='meetings', column_name='visit_location_label',
            constraint_name=None, datatype_name=None, schema_name='public',
        ),
    )
    return kind('INSERT INTO meetings VALUES (:private_phone)',
                {'private_phone': '+15559995555'}, original)


@pytest.mark.parametrize('phase', ['meeting_insert', 'booking_receipt_insert'])
def test_synthetic_data_error_is_annotated_and_propagated(phase):
    error = synthetic_error()
    session = FakeSession(error)
    with pytest.raises(DataError) as caught:
        checked_flush(session, phase)
    assert caught.value is error
    assert session.calls == 1
    result = structured_database_error(caught.value)
    assert result == {
        'dbapi_error': 'DataError', 'sqlstate': '22001', 'schema': 'public',
        'table': 'meetings', 'column': 'visit_location_label',
        'booking_phase': phase,
    }
    assert '555' not in str(result)
    assert 'INSERT' not in str(result)


def test_synthetic_enum_cast_error_is_classified_without_leaking_parameters():
    error = synthetic_error(state='22P02')
    assert structured_database_error(error)['sqlstate'] == '22P02'


def test_non_db_error_returns_none_and_clean_flush_is_unchanged():
    assert structured_database_error(ValueError('private')) is None
    session = FakeSession()
    checked_flush(session, 'meeting_insert')
    assert session.calls == 1
    with pytest.raises(ValueError):
        checked_flush(session, 'invalid_phase')
    assert session.calls == 1


def test_integrity_error_is_also_structured_safely():
    result = structured_database_error(synthetic_error(IntegrityError, '23505'))
    assert result['dbapi_error'] == 'IntegrityError'
    assert result['sqlstate'] == '23505'
    assert 'booking_phase' not in result


def synthetic_columns(max_length=40, enum_type=None):
    return [dict(table_name=table, column_name=column,
                 character_maximum_length=max_length,
                 data_type='USER-DEFINED' if enum_type and column == 'status' else 'character varying',
                 udt_name=enum_type if enum_type and column == 'status' else 'varchar')
            for table, column, value in EXPECTED_LITERALS]


def test_synthetic_schema_matching_literals_passes():
    assert inspect_literals(synthetic_columns(), {}) == []


def test_synthetic_schema_detects_overflow_and_missing_column():
    columns = synthetic_columns()
    columns = [dict(r) for r in columns if not (r['table_name'] == 'leads' and r['column_name'] == 'pipeline_stage')]
    for row in columns:
        if row['table_name'] == 'sales_conversations' and row['column_name'] == 'stage':
            row['character_maximum_length'] = 8
    found = inspect_literals(columns, {})
    assert {f['reason'] for f in found} == {'literal_exceeds_varchar', 'missing_column'}


def test_synthetic_pg_enum_label_drift_is_identified():
    columns = synthetic_columns(enum_type='meetingstatus')
    issues = inspect_literals(columns, {'meetingstatus': {'scheduled', 'confirmed'}})
    assert any(f['reason'] == 'enum_literal_unavailable' and
               f['table'] == 'meetings' for f in issues)
