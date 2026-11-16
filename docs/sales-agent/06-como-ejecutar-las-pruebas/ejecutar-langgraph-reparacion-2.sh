#!/usr/bin/env bash
# Same six synthetic journeys, shared live LangGraph; published-model balance is consumed.
set -uo pipefail
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
docker exec -i -w /app bp_api_prod python - <<'PY' || exit 1
import json
from app.core.config import settings
from app.modules.sales_agent.coordinator_graph import MODE,VERSION
from app.modules.sales_agent.observation_loop import VERSION as OBSERVATION
from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION
assert MODE=='graph-observe' and OBSERVATION=='sales-observation-loop/2.1'
assert SYSTEM_VERSION=='sales-interpretation-system/2.7'
print(json.dumps({'commit':settings.APP_COMMIT_SHA,'orchestrator':MODE,'coordinator':VERSION,'observation':OBSERVATION,'interpretation':SYSTEM_VERSION},indent=2))
PY
diagnostic_run="sales-graph-repair-2-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe \
  --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-graph-repair-2.zip" || exit 1
echo "Código de evaluación: $diagnostic_exit"
echo "Archivo generado: $HOME/sales-graph-repair-2.zip"
echo 'PowerShell:'
echo '& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-graph-repair-2.zip "$env:USERPROFILE\Downloads\sales-graph-repair-2.zip"'
exit "$diagnostic_exit"
