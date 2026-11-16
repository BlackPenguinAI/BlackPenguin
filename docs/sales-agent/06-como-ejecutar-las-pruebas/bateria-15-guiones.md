# Batería comercial de 15 guiones

Versión `sales-observation-battery/2.0`. Los seis originales mantienen mensajes y controles; la ampliación tiene nueve guiones separados como `expanded-nine`. Se mantiene la topología LangGraph compartida. La corrección posterior modifica interpretación acotada y continuación comercial; el histórico distingue código medido y pendiente de medir. Los fallos actuales de continuidad o interpretación temporal se reportan como FAIL, sin relajar controles para hacer pasar el motor.

| Grupo | ID | Recorrido |
|---|---|---|
| Base | obs_alternative | Fotos ausentes, brochure alternativo, cita. |
| Base | obs_mixed | Materiales o alternativa y financiamiento, cita. |
| Base | obs_switch | Cambio de propiedad y material correcto, cita. |
| Base | obs_interrupt | Materiales durante selección de horario, retoma. |
| Base | obs_time | Mañanas durante los próximos siete días. |
| Base | obs_no_seller | Indisponibilidad sin reserva ni espera automática. |
| Materiales | ext_gallery_pdf | Fotos, aceptación breve del PDF complementario, cita. |
| Materiales | ext_pdf_only | PDF sin galería, continuación comercial y consulta de distribución. |
| Consultiva | ext_pdf_financing | Brochure y financiamiento conocido, aceptación de galería pendiente. |
| Consultiva | ext_unknown_financing | Brochure, cuotas desconocidas, objeción de precio y presupuesto. |
| Preferencias | ext_bedroom_acceptance | Dos dormitorios ausentes, aceptar cuatro de forma contextual, elegir. |
| Preferencias | ext_compare_layout | Comparar dos opciones, elegir la segunda, preguntar distribución. |
| Agenda | ext_period_ordinal | Franja tarde o noche, seleccionar Option 3, confirmar. |
| Continuidad | ext_booked_questions | Reservar, consultar materiales y financiamiento, despedirse sin cancelar. |
| Continuidad | ext_long_recovery | 80 mensajes sintéticos anteriores con errores, retoma, materiales, aceptación breve y cita. |

Las franjas se seleccionan explícitamente con `--period-variant afternoon` o `evening`; quedan registradas. Se preparan bloques de disponibilidad de prueba compatibles. La corrección posterior define noches como 18:00–24:00. Su comportamiento con el modelo desplegado requiere una nueva corrida.

El historial largo está prefijado, identificado como semilla y no consume llamadas para generarlo. No representa todavía todos los cambios de preferencia y recursos ya enviados del mapa global. El guion de cita existente crea primero una reserva por el flujo normal y continúa después. Se registran puntuación, segmento, siguiente acción y motivo de parada de cadencia; las afirmaciones financieras y la pertinencia del segmento requieren revisión humana adicional.

Los guiones de conversación no exigen reserva. Los restantes usan el resumen y la confirmación normal. Un FAIL funcional no es un fallo del ejecutor de pruebas. Las pruebas locales usan proveedores simulados y no acreditan calidad comercial del modelo.

## Ejecutar después del despliegue, en SSH

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod

diagnostic_run="sales-15-afternoon-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite observation-battery --orchestrator graph-observe \
  --period-variant afternoon --max-calls 600 --max-turns 20 \
  --output "/tmp/$diagnostic_run"
diagnostic_exit=$?
docker cp "bp_api_prod:/tmp/$diagnostic_run/synthetic-sales-results.zip" "$HOME/sales-15.zip"
echo "Código de evaluación: $diagnostic_exit"
```

Estimación inicial de USD 0.25–0.60 total, sin garantía ni límite monetario; el historial largo y los reintentos pueden aumentarla. No ejecutar otra corrida nocturna completa todavía: revisar primero esta medición. Para medir solo ese caso usar `--cases ext_period_ordinal --period-variant evening` y otro directorio de salida.

En PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-15.zip "$env:USERPROFILE\Downloads\sales-15.zip"
```

Para repetir solo los seis originales usar `--cases obs_alternative obs_mixed obs_switch obs_interrupt obs_time obs_no_seller`.
