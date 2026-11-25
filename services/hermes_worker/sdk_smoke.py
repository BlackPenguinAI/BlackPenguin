"""Offline import-only smoke; never sends a request to OpenRouter."""
import importlib


def main():
    sdk = importlib.import_module('run_agent')
    registry = importlib.import_module('tools.registry')
    assert hasattr(sdk, 'AIAgent'), 'Pinned SDK missing AIAgent'
    assert callable(getattr(registry.registry, 'register', None)), 'SDK registry unavailable'
    assert callable(getattr(registry.registry, 'deregister', None)), 'SDK deregister unavailable'
    from app.modules.hermes_sales_core.p08_simulation import execute_staged_simulation
    assert callable(execute_staged_simulation)
    print('P08 SDK offline import smoke: PASS (no model/provider calls)')


if __name__ == '__main__':
    main()
