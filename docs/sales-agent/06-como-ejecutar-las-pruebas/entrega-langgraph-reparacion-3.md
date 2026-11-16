# Reparación integrada 3

Aplicar los archivos sobre la revisión `400593e05e379c4144e3269a69693a7e1ab25fb3`.

```bash
git add .
git commit -m "Fix property preference switches and combined commercial requests"
git push
```

Tras finalizar GitHub Actions, ejecutar en el servidor:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION; print(SYSTEM_VERSION); assert SYSTEM_VERSION == "sales-interpretation-system/2.8"'

diagnostic_run="sales-graph-repair-3-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe \
  --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?

docker cp \
  "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" \
  "$HOME/sales-graph-repair-3.zip"

echo "Código de evaluación: $diagnostic_exit"
echo "Archivo generado: $HOME/sales-graph-repair-3.zip"
```

En Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-graph-repair-3.zip "$env:USERPROFILE\Downloads\sales-graph-repair-3.zip"
```

Se repiten seis casos con el modelo publicado y leads guionados. Estimación total USD 0.10–0.20; el límite de llamadas no es un límite monetario. El laboratorio no contacta leads reales ni escribe en la base productiva. Las citas son de la base temporal; no prueba Calendar ni entrega Telnyx. La aprobación integral del diálogo sigue requiriendo revisión.
