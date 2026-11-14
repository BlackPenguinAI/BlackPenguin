#!/usr/bin/env bash
set -uo pipefail
diagnostic_run="sales-resumption-repair-2-$(date -u +%Y%m%dT%H%M%SZ)"
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/version
printf '\n'
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite continuity-battery \
  --cases resume_missing_visit resume_cedar_viewing resume_bay_see \
  --max-calls 120 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-resumption-repair-2.zip"
printf '\nCódigo de evaluación: %s\nArchivo: %s\n' "$diagnostic_exit" "$HOME/sales-resumption-repair-2.zip"
exit "$diagnostic_exit"
