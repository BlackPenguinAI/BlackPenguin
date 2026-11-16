#!/usr/bin/env bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.material_continuity import VERSION; print(VERSION)'

diagnostic_run="sales-material-continuity-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
 --suite observation-battery --orchestrator graph-observe \
 --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-material-continuity.zip"
echo "Código de evaluación: $diagnostic_exit"
