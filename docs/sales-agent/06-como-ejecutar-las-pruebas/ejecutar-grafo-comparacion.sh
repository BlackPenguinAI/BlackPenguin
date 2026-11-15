# Después de aplicar el ZIP en el repositorio local:
git add .
git commit -m "Add bounded graph experiments and scoped material recovery"
git push

# Por SSH, después de un despliegue correcto:
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

diagnostic_run="sales-graph-$(date -u +%Y%m%dT%H%M%SZ)"

for mode in classic graph-reconsider; do
  docker exec -i -w /app bp_api_prod \
    python -m tools.sales_ai.synthetic_lab \
    --suite continuity-battery \
    --orchestrator "$mode" \
    --cases resume_missing_visit resume_cedar_viewing resume_bay_see context_material_see context_visit_see \
    --max-calls 200 \
    --max-turns 10 \
    --output "/tmp/$diagnostic_run/$mode"
  echo "$mode: código de evaluación $?"
done

docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.compare_graph_runs \
  --reference "/tmp/$diagnostic_run/classic/synthetic-sales-results.zip" \
  --candidate "/tmp/$diagnostic_run/graph-reconsider/synthetic-sales-results.zip" \
  --output "/tmp/$diagnostic_run/sales-graph-comparison.zip"

docker cp \
  "bp_api_prod:/tmp/$diagnostic_run/sales-graph-comparison.zip" \
  "$HOME/sales-graph-comparison.zip"

# Desde Windows PowerShell, después de ver Successfully copied:
# & "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-graph-comparison.zip "$env:USERPROFILE\Downloads\sales-graph-comparison.zip"
