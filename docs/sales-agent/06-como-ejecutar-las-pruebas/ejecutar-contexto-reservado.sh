#!/usr/bin/env bash
# SSH del servidor; no detener antes de copiar un resultado FAIL.
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION; print(SYSTEM_VERSION); assert SYSTEM_VERSION == "sales-interpretation-system/2.9"'
diagnostic_run="sales-context-budget-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
 --suite observation-battery --orchestrator graph-observe \
 --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-context-budget.zip"
echo "Código de evaluación: $diagnostic_exit"
