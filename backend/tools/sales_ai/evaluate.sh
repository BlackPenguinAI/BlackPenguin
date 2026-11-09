#!/usr/bin/env bash
# Evaluation-only environment. Preserve an explicitly supplied inference key,
# never the application's production database or messaging credentials.
set -euo pipefail
BP_BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$BP_BACKEND_DIR"
exec env SECRET_KEY=isolated-model-evaluation ACCESS_TOKEN_EXPIRE_MINUTES=60 \
  DATABASE_URL=sqlite:// ENVIRONMENT=test FIRST_SUPERADMIN_EMAIL=test@example.invalid \
  FIRST_SUPERADMIN_PASSWORD=offline META_ACCESS_TOKEN=offline \
  SALES_DIALOGUE_RUNTIME_ENABLED=false SALES_NEXT_FLOW_ENABLED=false \
  SALES_UNDERSTANDING_PREVIEW_ENABLED=false SALES_NEXT_FLOW_PROJECT_IDS= \
  PYTHONPATH="$BP_BACKEND_DIR" "${BP_PYTHON:-python3}" -m tools.sales_ai.evaluate_model "$@"
