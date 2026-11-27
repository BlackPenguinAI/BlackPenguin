"""CI-only process serving the real private SDK endpoint on a disposable DB.

The readiness override is process-local, test-only, and never packaged into
production images. Do not use this process with real providers or customer data.
"""
from __future__ import annotations
from unittest.mock import patch
from guard import validate_environment, check_database, assert_scope


def main():
    mode = validate_environment(sdk=True)
    from app.db.postgres import engine
    from app.modules.hermes_sales_core import engine_selection, sdk_service
    from app.modules.hermes_sales_core.runtime import HermesSalesRuntime
    from app.modules.hermes_sales_core.contracts import TurnResult
    from sqlalchemy import text
    from run_lane import sdk_revision
    import uvicorn
    assert sdk_revision() == 'b94cb8e2c4ebf2a8c7688cf676c3cf9899584adb'
    assert engine_selection.live_hermes_ready() is False
    with engine.connect() as conn:
        check_database(conn)
    original_prepare = sdk_service.prepare_reserved
    original_runtime = HermesSalesRuntime.process_turn

    def guarded_prepare(db, request):
        check_database(db)
        assert_scope(db, request.job_id, request.run_id)
        return original_prepare(db, request)

    def measured_runtime(runtime, request):
        # Persist a test-only counter independently of the draft; a retry or
        # process restart cannot erase evidence of another model invocation.
        with engine.begin() as conn:
            check_database(conn)
            conn.execute(text('INSERT INTO hei06a_test_inference DEFAULT VALUES'))
        if mode == 'model':
            return original_runtime(runtime, request)
        prop = request.verified_context['focused_property']
        assert prop['display_name'] == 'Van Buren' and prop['bedrooms'] == 3
        return TurnResult('Van Buren has 3 bedrooms.', [], [])

    # Same endpoint, runtime, reservation and persistence implementations;
    # only the disposable fixture authorization and offline model are adapted.
    with patch.object(engine_selection, 'live_hermes_ready', return_value=True), \
         patch.object(sdk_service, 'prepare_reserved', guarded_prepare), \
         patch.object(HermesSalesRuntime, 'process_turn', measured_runtime):
        uvicorn.run(sdk_service.app, host='0.0.0.0', port=8080, workers=1,
                    proxy_headers=False, access_log=False, log_level='critical', lifespan='off')


if __name__ == '__main__':
    main()
