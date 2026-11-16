# Reconciliación del diálogo

Aplicar sobre `c9a90be23bcca935bb832fa8a795a26701a4c73d`.

```bash
git add .
git commit -m "Resolve contextual answers and offer verified complementary materials"
git push
```

Tras finalizar Actions, pegar en SSH:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION; from app.modules.sales_agent.material_continuity import VERSION; print(SYSTEM_VERSION,VERSION)'

diagnostic_run="sales-dialogue-reconciliation-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
 --suite observation-battery --orchestrator graph-observe \
 --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-dialogue-reconciliation.zip"
echo "Código de evaluación: $diagnostic_exit"
```

Debe imprimir `sales-interpretation-system/2.10` y `sales-material-continuity/2.0`.

Descarga en PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-dialogue-reconciliation.zip "$env:USERPROFILE\Downloads\sales-dialogue-reconciliation.zip"
```

Estimación total USD 0.10–0.20; no es un límite monetario. El caso de franja matutina todavía puede fallar. Luego repetir en la conversación real existente una aceptación de material, una selección ordinal y una despedida sin borrar su memoria. Exportar trazas de solo lectura. No reactivar seguimientos manualmente ni crear otra cita para comprobar la puntuación: la existente se reconoce al procesar el siguiente turno. Segmento puede permanecer desconocido legítimamente.
