# Continuidad comercial después de materiales

Aplicar sobre `db92e4e51095f081adccbee2dca414fb6c49105b`.

```bash
git add .
git commit -m "Preserve commercial continuity after material delivery"
git push
```

Tras finalizar GitHub Actions, pegar en SSH del servidor:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.material_continuity import VERSION; print(VERSION)'

diagnostic_run="sales-material-continuity-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
 --suite observation-battery --orchestrator graph-observe \
 --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-material-continuity.zip"
echo "Código de evaluación: $diagnostic_exit"
```

Descargar desde PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-material-continuity.zip "$env:USERPROFILE\Downloads\sales-material-continuity.zip"
```

Costo total estimado USD 0.10–0.20. No reintentar automáticamente una corrida fallida: conservarla para análisis. El fallo temporal conocido puede persistir; no se interpreta como corrección de esa parte. La evaluación no contacta leads reales.
