# Contexto reservado · entrega

Base `14bb98bdc1abcc4e21b70aeb48017c735fc9393e`. Aplicar el diferencial en la raíz del repositorio.

```bash
git add .
git commit -m "Reserve interpretation repair budget and validate contextual brochure acceptance"
git push
```

Cuando termine el despliegue, pegar en SSH del servidor:

```bash
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
```

En PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-context-budget.zip "$env:USERPROFILE\Downloads\sales-context-budget.zip"
```

Estimación USD 0.10–0.20 total para la batería corta; todavía no ejecutada con este cambio. No es un límite monetario. Luego probar en la conversación de WhatsApp existente un saludo y una búsqueda de dormitorios, sin borrar memoria. Exportar la evidencia con el diagnóstico de solo lectura anterior. Las conversaciones pagadas de 12–16 turnos no se ejecutan todavía.
