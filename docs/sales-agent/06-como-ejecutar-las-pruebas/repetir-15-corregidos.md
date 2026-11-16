# Repetir los 15 guiones después de la corrección

Aplicar el ZIP sobre el despliegue medido `69ae7fc`. Contiene cambios del motor compartido y del evaluador, y el histórico original sin cambiar sus resultados. No reiniciar conversaciones reales ni borrar su memoria.

En el repositorio local:

```bash
git add .
git commit -m "Repair commercial continuity and strengthen fifteen-case evaluation"
git push
```

Tras finalizar Actions, ejecutar en SSH:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

docker exec -i -w /app bp_api_prod python -c 'from app.modules.sales_agent.interpretation_input import SYSTEM_VERSION; from app.modules.sales_agent.material_continuity import VERSION; print(SYSTEM_VERSION, VERSION)'

diagnostic_run="sales-15-repair-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe \
  --period-variant afternoon --max-calls 600 --max-turns 20 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-15-repair.zip"
echo "Código de evaluación: $diagnostic_exit"
```

Versiones esperadas: `sales-interpretation-system/2.11` y `sales-material-continuity/2.1`. Mismo modelo publicado y mismos 15 guiones; se incorporan controles adicionales, por lo que también debe compararse cada control común. Un descenso por nuevos controles no demuestra por sí solo una regresión.

Presupuesto estimado de la repetición: USD 0.23–0.60 total, sin garantía ni tope monetario. No se hicieron llamadas pagadas locales. Primero revisar la corrida de tarde; la variante nocturna podrá medirse después con `--cases ext_period_ordinal --period-variant evening` en un directorio nuevo.

Descarga en PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-15-repair.zip "$env:USERPROFILE\Downloads\sales-15-repair.zip"
```
