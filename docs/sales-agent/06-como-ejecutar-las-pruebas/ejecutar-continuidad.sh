#!/usr/bin/env bash
# SSH: evaluación con datos aislados y el modelo publicado; no envía WhatsApp/SMS.
set -u
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/version
printf '\n'
diagnostic_run="sales-continuity-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite continuity-battery --max-calls 240 --max-turns 10 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-continuity.zip"
copy_exit=$?
printf '\nCódigo de evaluación: %s\nCódigo de copia: %s\nArchivo: %s\n' "$diagnostic_exit" "$copy_exit" "$HOME/sales-continuity.zip"
if [ "$copy_exit" -ne 0 ]; then exit "$copy_exit"; fi
exit "$diagnostic_exit"
