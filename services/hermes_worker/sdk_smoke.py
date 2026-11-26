"""Offline import-only smoke; never sends a request to OpenRouter."""
import importlib


def main():
    sdk = importlib.import_module('run_agent')
    registry = importlib.import_module('tools.registry')
    assert hasattr(sdk, 'AIAgent'), 'Pinned SDK missing AIAgent'
    assert callable(getattr(registry.registry, 'register', None)), 'SDK registry unavailable'
    assert callable(getattr(registry.registry, 'deregister', None)), 'SDK deregister unavailable'
    from app.modules.hermes_sales_core.p08_simulation import execute_staged_simulation
    from app.modules.hermes_sales_core.staged_runtime import execute_isolated_turn
    from app.modules.hermes_sales_core.engine_selection import live_hermes_ready
    from app.modules.hermes_sales_core.native_effects import execute_native_effect
    from app.modules.hermes_sales_core.production_tools import (
        execute_first_live_booking, persist_live_preferences, prepare_live_material_batch, material_delivery_receipt)
    assert all(callable(x) for x in (execute_first_live_booking, persist_live_preferences, prepare_live_material_batch, material_delivery_receipt))
    assert callable(execute_staged_simulation)
    assert callable(execute_isolated_turn)
    assert callable(execute_native_effect)
    from app.modules.hermes_sales_core.live_preparation import prepare_live_turn, reserve_live_run
    from app.modules.hermes_sales_core.live_receipts import commit_live_receipt
    from app.modules.hermes_sales_core.live_materials import issue_live_material_batch, complete_live_material_batch
    from app.modules.hermes_sales_core.live_coordinator import persist_live_draft, reconcile_live_reply, advance_live_effects
    assert all(callable(x) for x in (prepare_live_turn, reserve_live_run, commit_live_receipt,
        issue_live_material_batch, complete_live_material_batch, persist_live_draft, reconcile_live_reply, advance_live_effects))
    assert not live_hermes_ready(), 'HEI-03B continuation must not enable production Hermes'
    from app.modules.hermes_sales_core.sdk_service import app as private_app
    from app.modules.hermes_sales_core.live_job import process_hermes_inbound_job
    from app.modules.hermes_sales_core.provider_delivery import authorize_part
    assert callable(process_hermes_inbound_job) and callable(authorize_part)
    assert {route.path for route in private_app.routes} == {'/internal/prepare'}
    assert not live_hermes_ready(), 'The live gate must remain closed before certification'
    print('HEI-03B continuation SDK offline import smoke: PASS (no model/provider calls)')


if __name__ == '__main__':
    main()
