# Después de aplicar el ZIP, desde el repositorio local:
git add .
git commit -m "Fix contextual materials and focused visit clarification"
git push

# Después del despliegue correcto, ejecutar por SSH:
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

diagnostic_run="sales-material-clarification-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod \
  python -m tools.sales_ai.synthetic_lab \
  --suite continuity-battery \
  --cases resume_missing_visit resume_cedar_viewing resume_bay_see context_material_see context_visit_see \
  --max-calls 200 \
  --max-turns 10 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?

docker cp \
  "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" \
  "$HOME/sales-material-clarification.zip"
echo "Código de evaluación: $diagnostic_exit"
echo "Archivo: $HOME/sales-material-clarification.zip"

# En Windows PowerShell (ejecutar allí, no en SSH):
# & "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-material-clarification.zip "$env:USERPROFILE\Downloads\sales-material-clarification.zip"
