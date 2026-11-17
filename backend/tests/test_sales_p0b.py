"""Shared pure synthetic P0-B cases; run locally with pytest.

Importable tests are also packaged in tools/ for production-container
self-testing, since the Docker image does not copy backend/tests.
"""
from tools.sales_ai.p0b_selftest import TestSyntheticBookingAcceptance, TestSyntheticBookingWire
