# Compact Repair 3: interpretación coherente y diagnóstico conservado

Base: `2d85c207292cc2e25edc796168317e9713f0e274` (Repair 2).

## Evidencia y alcance

La corrida de servidor `sales-compact-repair-2.zip` tuvo 31 turnos, siete `TypeError` sin pila ni evento de interpretación conservado, y cero de cuatro visitas esperadas. Las respuestas guardadas muestran propietarios de materiales clasificados como materiales, solicitudes de visita sin request asociado y visitas nuevas clasificadas como consultas de citas existentes.

No se conoce todavía la función que originó los siete `TypeError`: el diagnóstico anterior se perdió con el rollback. Las pruebas de esta entrega provocan esa clase de fallo para reproducir la pérdida de información; no reconstruyen paquetes ausentes ni prueban la causa exacta de producción.

## Cambios

- La interpretación conserva en memoria el diario y las ubicaciones de código antes del rollback. También conserva un preview exitoso si falla después la planificación. El run fallido exporta la traza y los intentos recibidos, acotados como los diagnósticos existentes. No se exporta el texto de excepciones, parámetros SQL ni credenciales.
- Tras un fallo inesperado se vuelven a validar autorización, aislamiento y continuidad antes de conservar declaraciones literales del mensaje actual. Se conserva presupuesto/moneda/financiación/motivación verificables; no se ejecutan herramientas ni se inventan solicitudes. La segmentación se proyecta sobre esos datos sin marcar fondos verificados.
- Una propiedad mencionada de forma exacta y única en una solicitud de material se usa como su propietario cuando el modelo la clasificó como material. Se mantiene la selección y autorización de recursos existente.
- Una petición literal afirmativa de nueva visita conserva request y directiva y no se trata como consulta de citas existentes. Se excluyen mensajes reportados, hipotéticos, negativos y cambios de citas. Seleccionar un slot y confirmar siguen siendo pasos separados.
- “Any available time” no exige un rango horario vacío. Rechazar una visita propuesta no cancela una reserva existente.
- El prompt explica esas diferencias. La evaluación detecta la respuesta incorrecta que ofrece cancelar/cambiar una cita al rechazar una visita nueva.

No cambia el modelo, las dependencias, las migraciones ni el transporte de mensajes.

## Validación local

Las pruebas reproducen únicamente paquetes que existen en la evidencia; los siete paquetes ausentes no se presentan como evidencia reconstruida. El resto de recorridos usa respuestas HTTP simuladas, sin gasto de inferencia. Incluyen las dos configuraciones de autoflush del laboratorio, información/material/visita/confirmación, rechazo y fallos en interpretación y planificación, verificando que no se generen citas ni outbox en los fallos.

Regresión completa en tres shards: 2.980 pruebas aprobadas, siete omitidas y cero fallos. Cobertura de módulos verificada. Aceptación técnica: 63 PASS, cero FAIL y una prueba live pendiente. Tras añadir dos límites de ambigüedad, se repitió el módulo específico completo: 52 pruebas aprobadas. Estas 52 se solapan con la regresión y no se suman a su total. Estos controles técnicos no equivalen a calidad medida con el modelo publicado.

## Corrida puntual después de desplegar

Tres casos: `first_time_A` (PDF y visita), `move_up_B` (cambio de propiedad, galería y rechazo), `unknown_A` (visita sin segmento). Se esperan dos visitas; máximo ocho turnos por caso y sesenta llamadas globales. El límite cuenta llamadas, no dólares. Mantener la configuración publicada actual para comparar el controlador con el mismo modelo.

SSH:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B unknown_A \
  --max-calls 60 --max-turns 8 \
  --output /tmp/sales-compact-repair-3
```

Copiar incluso si el resultado es `FAIL`:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-3/synthetic-sales-results.zip ~/sales-compact-repair-3.zip
```

PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-3.zip "$env:USERPROFILE\Downloads\sales-compact-repair-3.zip"
```

Es una simulación aislada ejecutada desde el contenedor: lee la configuración publicada y llama al proveedor, pero usa SQLite desechable, no escribe leads/citas en producción, no envía SMS/WhatsApp ni contacta Google Calendar. No prueba concurrencia PostgreSQL, entrega por operador ni calidad de toda la batería. Si vuelve a ocurrir un `TypeError`, revisar `output.error_diagnostic` y `input_trace.interpretation_failure` antes de atribuir una causa o ampliar la corrida.

## Aplicación

Copiar los archivos del ZIP respetando sus rutas desde la raíz del repositorio. No hay archivos para eliminar.

```bash
git pull && git add . && git commit -m "Preserve sales failure diagnostics and normalize explicit material and visit requests" && git push
```
