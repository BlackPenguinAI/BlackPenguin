"""Include P2-A compiled-graph safety and isolation checks in backend CI."""
from tools.sales_ai.p2a_compile_selftest import (  # noqa: F401
    TestP2ACompiledGraph,
    TestP2AInvocationIsolation,
    TestP2AProductionWiring,
)
