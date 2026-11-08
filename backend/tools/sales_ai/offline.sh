#!/usr/bin/env bash
# Child-process test configuration only. Do not source this file.
set -euo pipefail
BP_BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BP_PYTHON="${BP_PYTHON:-python3}"
cd "$BP_BACKEND_DIR"
BP_MODE="${1:-test}"
case "$BP_MODE" in
    test) BP_ARGS=(-m pytest tests/test_sales_ai_group_a.py -q --disable-warnings) ;;
    group-b) BP_ARGS=(-m pytest tests/test_sales_ai_group_b.py -q --disable-warnings) ;;
    group-c) BP_ARGS=(-m pytest tests/test_sales_ai_group_c.py -q --disable-warnings) ;;
    group-d) BP_ARGS=(-m pytest tests/test_sales_ai_group_d.py -q --disable-warnings) ;;
    group-e) BP_ARGS=(-m pytest tests/test_sales_ai_group_e.py -q --disable-warnings) ;;
    baseline) BP_ARGS=(-m pytest tests -q --disable-warnings) ;;
    replay) BP_ARGS=(-m tools.sales_ai.replay --output "${2:?Provide the report output path}") ;;
    *) printf 'Usage: bash tools/sales_ai/offline.sh test|group-b|group-c|group-d|group-e|baseline|replay OUTPUT\n' >&2; exit 2 ;;
esac
exec env SECRET_KEY=group-a-offline-test ACCESS_TOKEN_EXPIRE_MINUTES=60 \
    DATABASE_URL=sqlite:// ENVIRONMENT=test \
    FIRST_SUPERADMIN_EMAIL=test@example.invalid FIRST_SUPERADMIN_PASSWORD=offline-only \
    META_ACCESS_TOKEN=offline-only OPENROUTER_API_KEY=offline-only DIALOGUE_POSTGRES_TEST_URL= \
    SALES_DIALOGUE_RUNTIME_ENABLED=false SALES_UNDERSTANDING_PREVIEW_ENABLED=false \
    SALES_NEXT_FLOW_ENABLED=false SALES_NEXT_FLOW_PROJECT_IDS= \
    APP_COMMIT_SHA=f7e7f055fd0499f2224b43bad8f9128db2eaf434 PYTHONPATH="$BP_BACKEND_DIR" \
    "$BP_PYTHON" "${BP_ARGS[@]}"
