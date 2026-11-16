# Reparación 2 del motor integrado

Base: `91e902aab45e9602830dabd72778430241d6527c`. Extraer el diferencial sobre la raíz del repositorio. No requiere migración ni cambio de modelo/configuración publicada.

```bash
git add .
git commit -m "Fix scoped material requests without redundant clarification"
git push
```

Tras completar GitHub Actions, seguir `ejecutar-langgraph-reparacion-2.sh` o ejecutar sus comandos en el servidor. Verifica dentro del contenedor `sales-interpretation-system/2.7` y `sales-observation-loop/2.1`; evita el endpoint HTTP que puede requerir autenticación.

```bash
diagnostic_run="sales-graph-repair-2-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe \
  --max-calls 300 --max-turns 10 --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-graph-repair-2.zip"
echo "Código de evaluación: $diagnostic_exit"
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-graph-repair-2.zip "$env:USERPROFILE\Downloads\sales-graph-repair-2.zip"
```

Presupuesto orientativo por corrida: USD 0.10–0.20. Las 300 llamadas son un límite de llamadas, no un límite en dólares. Son seis conversaciones sintéticas, con cinco citas esperadas y sin contactos externos. No prueban entrega Telnyx/Calendar ni concurrencia PostgreSQL.

Para la prueba manual, enviar un mensaje nuevo al lead de prueba: solicitar el folleto de una propiedad aprobada y repetir después de cambiar a otra. Debe compartir el material correcto si está aprobado y disponible, o explicar su falta/solicitar una aclaración real. No debe preguntar si se desea lo que ya se pidió. Para las variantes negativas (propietario desconocido, nombres ambiguos, negaciones), debe conservar la restricción o pedir aclaración. No se reenvían automáticamente mensajes históricos al desplegar.

El README principal del laboratorio contiene la evolución real hasta 5/6, su consumo y la evidencia legible. El replay local no se añade al gráfico como nueva medición del modelo publicado.
