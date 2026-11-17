"""P0 synthetic offline smoke for production Docker images (no pytest required).

Run: python -m tools.sales_ai.p0_booking_selftest
No database connection, OpenRouter call, outbound message, or booking.
"""
import unittest
from types import SimpleNamespace
from sqlalchemy.exc import DataError
from app.modules.sales_agent.booking_p0 import checked_flush, structured_database_error
from .p0_booking_schema_probe import inspect_literals, EXPECTED_LITERALS


class FakeOriginal(Exception):
    def __init__(self, state):
        super().__init__('PRIVATE DATA THAT MUST NEVER BE LOGGED')
        self.pgcode = state
        self.diag = SimpleNamespace(schema_name='public', table_name='meetings',
                                    column_name='visit_location_label',
                                    constraint_name=None, datatype_name=None)


class SessionStub:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def flush(self):
        self.calls += 1
        if self.error:
            raise self.error


class TestSyntheticBookingP0(unittest.TestCase):
    def test_booking_meeting_phase(self):
        error = DataError('PRIVATE SQL', {'private_phone': '+1999'}, FakeOriginal('22001'))
        session = SessionStub(error)
        with self.assertRaises(DataError):
            checked_flush(session, 'meeting_insert')
        info = structured_database_error(error)
        self.assertEqual(info['booking_phase'], 'meeting_insert')
        self.assertEqual(info['sqlstate'], '22001')
        self.assertNotIn('PRIVATE', repr(info))

    def test_booking_receipt_phase(self):
        error = DataError('PRIVATE SQL', {'private_phone': '+1999'}, FakeOriginal('22P02'))
        with self.assertRaises(DataError):
            checked_flush(SessionStub(error), 'booking_receipt_insert')
        self.assertEqual(structured_database_error(error)['booking_phase'], 'booking_receipt_insert')
        self.assertEqual(structured_database_error(error)['sqlstate'], '22P02')

    def test_flush_success_unmodified(self):
        session = SessionStub()
        checked_flush(session, 'meeting_insert')
        self.assertEqual(session.calls, 1)

    def test_no_database_leak(self):
        self.assertIsNone(structured_database_error(ValueError('LEAD PRIVATE')))

    def test_synthetic_schema_mismatch(self):
        rows = [dict(table_name=t, column_name=c, data_type='character varying',
                     character_maximum_length=40, udt_name='varchar')
                for t, c, _ in EXPECTED_LITERALS]
        self.assertEqual(inspect_literals(rows, {}), [])
        for row in rows:
            if row['table_name'] == 'sales_conversations' and row['column_name'] == 'stage':
                row['character_maximum_length'] = 10
        self.assertIn('literal_exceeds_varchar',
                      {v['reason'] for v in inspect_literals(rows, {})})


if __name__ == '__main__':
    unittest.main(verbosity=2)
