#!/usr/bin/env bash
set -uo pipefail
diagnostic_run="sales-visit-context-$(date -u +%Y%m%dT%H%M%SZ)"
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite continuity-battery \
  --cases resume_missing_visit resume_cedar_viewing resume_bay_see context_material_see context_visit_see \
  --max-calls 200 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-visit-context.zip"
printf '\nCódigo: %s\nArchivo: %s\n' "$diagnostic_exit" "$HOME/sales-visit-context.zip"
exit "$diagnostic_exit"
