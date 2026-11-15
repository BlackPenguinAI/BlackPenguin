# En el repositorio local, después de extraer el ZIP:
git add .
git commit -m "Fix scoped read references and verified visit confirmations"
git push

# Por SSH, cuando GitHub Actions termine correctamente:
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/version

diagnostic_run="sales-observation-repair-2-$(date -u +%Y%m%dT%H%M%SZ)"
for mode in classic graph-observe; do
  docker exec -i -w /app bp_api_prod \
    python -m tools.sales_ai.synthetic_lab \
    --suite observation-battery \
    --orchestrator "$mode" \
    --max-calls 300 \
    --max-turns 10 \
    --output "/tmp/$diagnostic_run/$mode"
  diagnostic_exit=$?
  echo "$mode: código de evaluación $diagnostic_exit"
done

docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.compare_graph_runs \
  --reference "/tmp/$diagnostic_run/classic/synthetic-sales-results.zip" \
  --candidate "/tmp/$diagnostic_run/graph-observe/synthetic-sales-results.zip" \
  --output "/tmp/$diagnostic_run/sales-observation-repair-2-comparison.zip"

docker cp \
  "bp_api_prod:/tmp/$diagnostic_run/sales-observation-repair-2-comparison.zip" \
  "$HOME/sales-observation-repair-2-comparison.zip"

# Windows PowerShell, después de Successfully copied:
# & "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-observation-repair-2-comparison.zip "$env:USERPROFILE\Downloads\sales-observation-repair-2-comparison.zip"
