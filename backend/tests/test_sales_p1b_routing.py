"""Run P1-B specialist routing and wiring in the normal backend CI partition."""
from tools.sales_ai.p1b_routing_selftest import (  # noqa: F401
    TestP1BClassifier,
    TestP1BGraph,
    TestP1BWiring,
)
