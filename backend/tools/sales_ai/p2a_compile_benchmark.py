"""Offline microbenchmark of compile vs cached lookup (no model/DB/messages).

Run from /app: python -m tools.sales_ai.p2a_compile_benchmark --iterations 100
The numbers only reflect this process/machine; not LLM tokens or end-to-end latency.
"""
import argparse
import json
from statistics import median
from time import perf_counter_ns
from app.modules.sales_agent.coordinator_graph import _build_compiled_graph, compiled_graph


def samples(action, n):
    durations = []
    for _ in range(n):
        started = perf_counter_ns()
        action()
        durations.append((perf_counter_ns() - started) / 1_000_000)
    return durations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    if not 10 <= args.iterations <= 1000:
        parser.error('--iterations must be between 10 and 1000')
    compiled_graph()  # Warm process cache outside the measured loop.
    # The comparison repeats only the old build+compile work, never a turn.
    built = samples(_build_compiled_graph, args.iterations)
    cached = samples(compiled_graph, args.iterations)
    result = {
        'version': 'sales-p2a-graph-compile-benchmark/1.0',
        'iterations': args.iterations,
        'compile_each_turn_median_ms': round(median(built), 6),
        'cached_lookup_median_ms': round(median(cached), 6),
        'provider_calls': 0, 'database_writes': 0,
        'production_latency_measured': False,
        'note': 'Graph construction/compilation only; not an end-to-end response benchmark.'
    }
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
