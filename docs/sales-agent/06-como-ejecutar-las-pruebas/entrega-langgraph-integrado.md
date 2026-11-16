# Aplicar y comprobar el motor único

Base del diferencial: `cb302013b764f2102b7959eb195f35cba7a8212d`.
Extraer el ZIP sobre la raíz del repositorio local. No requiere migración de base de datos. Publicar:

```bash
git add .
git commit -m "Integrate commercial LangGraph engine across live channels and experiments"
git push
```

Esperar a que GitHub Actions termine y comprobar API **y worker**:

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/sales-engine
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/sales
```

Esperado: ambos contenedores en el nuevo commit; `engine=sales-langgraph/2.0`, `orchestrator=graph-observe`, `coordinator_version=sales-coordinator-graph/2.0`. La identidad desplegada no demuestra por sí sola ejecución de un turno ni entrega al teléfono.

Ejecutar solamente el nuevo motor, sin referencia clásica:

```bash
diagnostic_run="sales-langgraph-integrated-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe --max-calls 300 --max-turns 10 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp \
  "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" \
  "$HOME/sales-langgraph-integrated.zip"
echo "Código de evaluación: $diagnostic_exit"
```

PowerShell de Windows:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-langgraph-integrated.zip "$env:USERPROFILE\Downloads\sales-langgraph-integrated.zip"
```

Son seis casos sintéticos con cinco citas esperadas, base temporal y sin mensajes externos. Usan la configuración de ventas publicada; estimación $0.10–$0.20 por corrida, no un límite de gasto. No certifican calidad comercial integral, transporte ni Google Calendar.

Para probar manualmente, usar un lead de prueba con consentimiento en un proyecto aprobado: consulta por dormitorios → selección de propiedad → materiales → solicitud de visita → selección de horario → confirmación. También probar una duda entre la oferta de horarios y su selección. No asumir que todas las casuísticas reales ya están resueltas por integrar el motor.

Después, exportar la conversación **sin reejecutarla**. Sustituir `ID_DE_LA_CONVERSACION` por el ID de esa conversación:

```bash
diagnostic_run="sales-live-langgraph-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.inspect_commercial_graph \
  --conversation-id ID_DE_LA_CONVERSACION --limit 30 --output "/tmp/$diagnostic_run.zip"
docker cp "bp_api_prod:/tmp/$diagnostic_run.zip" "$HOME/sales-live-langgraph.zip"
```

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-live-langgraph.zip "$env:USERPROFILE\Downloads\sales-live-langgraph.zip"
```

El informe separa la versión desplegada del motor de cada turno histórico. Un turno nuevo completo debe registrar `interpret`, `plan`, `observe`, `fulfill`. El ciclo registra decisiones, consultas, observaciones y límite de rondas. Los errores anteriores no se reescriben ni se reenvían al desplegar. Eventos históricos inconclusos de otro motor requieren conciliación; no se reinterpretan automáticamente para evitar duplicar efectos.

Enviar los dos ZIP cuando estén disponibles. Primero revisaremos la equivalencia efectiva del motor, luego resultados funcionales, seguridad y calidad comercial. No hay llamadas pagadas locales en esta entrega; las pruebas de red están simuladas.
