# Iteración puntual de agendamiento

Base: 2943c65c11125786736bf47e1e95bc790410975e. Esta entrega añade un modo al laboratorio; no cambia el agente de producción ni sus prompts.

## Alcance

Seis compradores guionizados, sin modelo comprador ni juez:

1. Sales con acceso a todos los proyectos y horarios.
2. Sales con acceso a un proyecto y horarios.
3. Sales sin proyectos con horarios: nunca elegible.
4. Ningún sales elegible.
5. Sales elegible sin horarios.
6. Rechazo de la primera opción y selección de la segunda antes de reservar.

Se conservan los tres proyectos y seis propiedades del catálogo anterior. Las seis conversaciones se concentran en Bay Residence / Harbor Gardens para aislar el agendamiento. No representan aún los ocho segmentos. Cada caso usa vendedores distintos para que sus reservas no contaminen los siguientes. Se reconstruyen las asignaciones y los bloques de disponibilidad entre casos, mediante `sync_user_project_access` y las reglas reales de elegibilidad. No se cargan usuarios, leads ni calendarios de producción.

Los horarios se generan dos, tres y cuatro días después de la referencia UTC de cada caso; los diálogos avanzan diez segundos por turno. La referencia se exporta. El comprador solo lee texto público: elige una opción con fecha, hora y zona, y responde Yes únicamente después del resumen de confirmación y una selección previa. Nunca recibe IDs privados de slots, propuestas ni reservas. El objetivo es verificar el núcleo; la calidad de la interpretación con el modelo publicado se mide al ejecutar en servidor.

## Ejecución sin costo

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point --prepare-only --max-turns 8 \
  --output /tmp/sales-booking-point-preview
```

## Ejecución con la configuración publicada

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-1
```

El padre lee exclusivamente la configuración global publicada y su credencial en una transacción de solo lectura. El hijo usa SQLite y almacenamiento privados temporales. El guard de red solo permite inferencia OpenRouter; no se envían SMS, WhatsApp, correo ni llamadas a Google Calendar. Las credenciales se eliminan del reporte.

120 es un máximo global de llamadas, distribuido en seis cuotas de 20. Es un límite de llamadas, no un límite monetario. El precio real depende del modelo publicado, contexto y reintentos. La estimación anterior no sustituye el consumo reportado. Si una cuota se agota, el caso no se considera aprobado. Para repetir, cambiar el sufijo de la carpeta: se exige una carpeta vacía.

Una salida 2 indica FAIL, INCOMPLETE o ERROR y conserva los archivos. Continuar con la copia aunque las conversaciones fallen: justamente necesitamos analizarlas.

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-1/synthetic-sales-results.zip ~/sales-booking-point-1.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-1.zip "$env:USERPROFILE\Downloads\sales-booking-point-1.zip"
```

## Evidencia

`report.json`, `report.md`, `summary.json`, catálogo y recursos sintéticos. Se registra commit, modelo, versión y hash de configuración, referencia temporal, cada mensaje, interpretación, traza y salida, resultado de las verificaciones y reservas persistidas antes de limpiar los datos temporales. La conversación se detiene al reservar o al alcanzar su límite. Los casos sin disponibilidad observan dos respuestas y requieren revisión humana del cierre; se marcan INCOMPLETE si todas las otras comprobaciones pasan.

Se verifica que exista exactamente la reserva esperada, que se haya seleccionado y confirmado, vendedor elegible, proyecto/lead correcto, dirección, hora coincidente con la selección pública, confirmación pública coherente, ausencia de outbox externo y repetición idempotente del mismo evento. Las reservas las crea el coordinador real; el guion y evaluador no las insertan.

## Límites explícitos

- Se usa el modo de simulación vigente. No se afirma validar integración Google Calendar, reparto round-robin de producción, bloqueos concurrentes PostgreSQL ni transporte WhatsApp/SMS.
- No se falsifica un evento de Google Calendar exitoso. El reporte conserva el estado real de calendario de la reserva sintética.
- La función de reparto se verifica por separado con los vendedores sintéticos; la simulación conserva sus diferencias de ejecución.
- La comprobación de disponibilidad no acredita por sí sola el texto correcto de aviso de futuros horarios. Revisión humana pendiente; no existe alta en una lista de espera ni notificación automática en esta entrega.
- No hay cancelaciones ni reagendamientos. Elegir otra opción antes de confirmar la primera reserva es parte del agendamiento inicial.
- Las pruebas offline con respuestas HTTP controladas verifican que el laboratorio ejecuta el coordinador y persiste reservas. No demuestran calidad del modelo real. La siguiente corrida produce esa evidencia.

## Validación de la entrega

Pruebas offline del piloto, laboratorio previo y flujos de visita: se verifican los seis escenarios con el coordinador real y respuestas HTTP controladas. Se comprueba también que un proveedor incapaz de interpretar visitas produzca fallos exportables, sin fabricar reservas. La calidad con el modelo publicado queda pendiente de ejecutar el comando anterior.

Observación del código vigente: `wait_service` ya ofrece solicitar consentimiento para un aviso de nuevos horarios. Los guiones sin disponibilidad rechazan expresamente configurar la alerta. Su funcionamiento completo no se evalúa en esta iteración.
