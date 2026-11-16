#!/usr/bin/env bash
# Run from the server. Disposable synthetic database; published model consumes OpenRouter balance.
set -uo pipefail
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
docker exec -i -w /app bp_api_prod python -c 'import json; from app.modules.health.router import sales_engine; print(json.dumps(sales_engine(),indent=2))' || exit 1
diagnostic_run="sales-langgraph-integrated-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe --max-calls 300 --max-turns 10 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-langgraph-integrated.zip" || exit 1
echo "Código de evaluación: $diagnostic_exit"
echo "Archivo: $HOME/sales-langgraph-integrated.zip"
echo 'Windows PowerShell:'
echo '& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-langgraph-integrated.zip "$env:USERPROFILE\Downloads\sales-langgraph-integrated.zip"'
exit "$diagnostic_exit"
