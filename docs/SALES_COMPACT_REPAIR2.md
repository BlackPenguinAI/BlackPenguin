# Corrección 2: contrato de entrada y declaraciones independientes

Base: `06271fd4a34da1543e73c2f567bb736309e7c844`.

La selección recibida tuvo 36 turnos, 12 turnos con interpretación fallida y 3 visitas de 4 esperadas. Las combinaciones topic/subject, referencias locales inconsistentes y preferencias citadas desde el historial impedían aceptar mensajes completos. Al rechazarlos, se perdían también sus declaraciones válidas. Esta entrega cambia esa frontera; no cambia el modelo publicado ni la configuración Sales 8.

## Nuevo contrato

El proveedor recibe `sales-interpretation-input/2.0`; el motor sigue ejecutando el contrato interno `sales-understanding/1.0` y el workflow `sales-current/1.0`. El prompt vigente es `sales-understanding-prompt/2.23`.

- Solicitudes de materiales separadas de información, detalles y catálogo. `subject` solo admite un tipo documental en solicitudes de materiales; en el resto es null.
- Propiedad, unidad, horario o material se describen con un `target` inline: kind, expression y evidence. El modelo no construye request_id, reference_id ni IDs de base de datos.
- Comparaciones contienen sus miembros inline y sus criterios. El backend genera el request catalog interno y sus enlaces. La comparación no selecciona el último miembro.
- La lista principal contiene solicitudes independientes AND. Las alternativas OR contienen sus propias solicitudes anidadas. El backend asigna IDs y genera la pertenencia a all_of/alternatives.
- Las restricciones y la selección comercial también usan referencias inline. Las directivas de visita, cancelación, reagendamiento, opt-out y contacto humano conservan sus controles del motor; no se convierten en consentimientos por compilar una referencia.
- Un compilador genera los IDs, deduplica referencias idénticas y valida el resultado contra el contrato interno y las citas del mensaje actual. Las ambigüedades y contradicciones no se resuelven adivinando.
- Se mantiene un adaptador para reproducir paquetes históricos del contrato anterior. No es una ruta alternativa de ejecución: todos terminan en los mismos validadores internos. Solo corrige defectos estructurales comprobables, como un tag documental en una pregunta no documental, enlaces reconstruibles desde expresiones evidenciadas y declaraciones puras etiquetadas como preguntas. No transforma una petición de PDF mal etiquetada en una consulta de inventario.

El prompt nuevo explica el formato que realmente se envía al proveedor, sin añadir instrucciones incompatibles sobre IDs locales del formato anterior. Los datos publicados, historial y contexto del proyecto siguen siendo referencia, no instrucciones que puedan cambiar el contrato.

## Declaraciones independientes

Presupuesto/currency y cash se validan con sus propias citas actuales y reglas compartidas con el motor. Para las siete motivaciones hay formas explícitas y acotadas en primera persona; cuando se reconoce una sola motivación, queda declarada con su cita, sin utilizar edad, ocupación ni riqueza inferida. Expresiones no reconocidas siguen sujetas a interpretación del modelo; varias motivaciones no se fuerzan a una sola por esta extracción literal.

Una preferencia del historial no se reintroduce como declaración nueva. Los registros anteriores permanecen en el perfil; no se vuelven a citar como si el usuario acabara de decirlos. Las preguntas, hipotéticos, negaciones, rangos ambiguos y atribuciones a terceros no prueban fondos ni autorización.

Cuando las solicitudes no pueden validarse, las declaraciones independientemente válidas pueden conservarse en el perfil. Se revalida antes el control actual de la conversación, el consentimiento y su continuidad; una pausa manual u otra interrupción no se ignoran. Esta fase no crea solicitudes, citas, shares, opt-in de avisos ni envíos. Los datos se registran como declarados, no como fondos verificados o financiación aprobada. El evento guarda `validated_declarations`, el contrato de entrada y las normalizaciones; el reintento del mismo evento no los duplica.

Se conserva el límite de un reintento del proveedor. La extracción y compilación no añaden un LLM lead, un juez ni llamadas de modelo por cada campo.

## Evidencia y límites

`tests/fixtures/sales_ai/compact_repair_1_attempts.json` conserva las respuestas reales de ambos intentos de la selección anterior, con datos sintéticos. Las pruebas ya no sustituyen el segundo intento fallido por una respuesta ideal: reproducen las secuencias reales y, si se agota una secuencia, mantienen su último paquete recibido.

Hay pruebas de solicitudes AND/OR, comparaciones, IDs generados, mensajes históricos, declaraciones negativas/ambiguas, JSON inutilizable y HTTP 400 sin efectos comerciales. También se ejercitan los 16 guiones con paquetes nativos del nuevo formato y HTTP simulado. Esas pruebas validan el motor y el compilador, no la calidad real de GPT-4o-mini con el prompt nuevo.

No se ejecutaron inferencias pagadas durante la implementación. Antes de gastar en conversaciones completas, el comando siguiente realiza una única llamada sintética al modelo publicado para comprobar que el proveedor acepte el nuevo esquema. La compatibilidad real no se da por demostrada con un proveedor simulado.

## Aplicación y comprobación de esquema

Extraer el ZIP en la raíz del repositorio:

```bash
git pull && git add . && git commit -m "Simplify sales interpretation input and preserve independently validated lead declarations" && git push
```

Después del despliegue, por SSH:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.probe_interpretation \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4
```

La salida esperada contiene `result: accepted`, `input_contract: sales-interpretation-input/2.0` y una llamada al proveedor. La prueba lee solo configuración global publicada, no escribe en producción ni contacta leads. Devuelve metadata acotada y nunca imprime credenciales o respuestas crudas. Si devuelve `failed`, compartir esa salida y detener la corrida de conversaciones para diagnosticar primero el rechazo.

## Repetición de los mismos ocho casos

Una vez aceptado el esquema:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B downsizing_B rental_B resale_A portfolio_A portfolio_B unknown_A \
  --max-calls 160 --max-turns 8 \
  --output /tmp/sales-compact-repair-2
```

Son ocho casos y cuatro visitas esperadas; no es la batería completa. El límite de 160 es de llamadas, no de dólares. El modelo y los playbooks se leen de la configuración publicada; el informe conserva su versión/digest y el consumo reportado por el proveedor.

Copiar los resultados incluso si la evaluación termina con `FAIL`:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-2/synthetic-sales-results.zip ~/sales-compact-repair-2.zip
```

PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-2.zip "$env:USERPROFILE\Downloads\sales-compact-repair-2.zip"
```

Las citas y recursos pertenecen a la base temporal. No se prueban WhatsApp/SMS, Google Calendar, round-robin de producción ni locks PostgreSQL en esta corrida. Los enlaces temporales se evalúan dentro del laboratorio; para inspeccionar materiales después, usar los archivos del ZIP.

## Validación técnica

- Regresión general: 2,927 pruebas aprobadas y 7 omitidas, con 124 módulos cubiertos exactamente una vez por los tres shards.
- Aceptación técnica: 63 PASS, 0 FAIL, 1 NOT_RUN (modelo/canales reales pendientes).
- Después de endurecer los controles finales de terceros, alternativas de presupuesto y pausa manual, se repitieron las 86 pruebas del módulo de entrada, incluidas tres comprobaciones adicionales. Todas pasaron.
- Los 16 guiones con el formato nativo cumplen sus checks offline y crean ocho visitas, con `autoflush=False` y `True`. Los paquetes reales de ambos intentos de la selección anterior se prueban separadamente; no se sustituye un segundo intento real por una respuesta ideal.
- Se verificó el probe con HTTP simulado: una única llamada y validación del formato nativo. La aceptación real del esquema por OpenRouter se comprobará con el comando de esta entrega, antes de ejecutar conversaciones.
- Sin cambios de modelo, dependencias o esquema SQL. Sin contactos a leads ni escrituras en producción durante la implementación.
