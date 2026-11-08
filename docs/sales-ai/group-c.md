# Sales AI — Grupo C: pasos 5 y 6

Fecha: 8 de noviembre de 2026. Base: `5ec0c2875260b699ba0bdb5364a3b6a3f65dd9dc`.
Rama: `sales-ai/group-c-profile-context`. Continúa A, su fix de Actions y B.
Próximo grupo: **D, pasos 7 y 8**, todavía pendiente. Resultados: `group-c-report.json`.

## Paso 5 — Perfil comercial con evidencia

`lead_profile.resolve` compone una vista por turno de `meta_form_data`, el formato
Graph `field_data`, `source_answers`, hechos legados y declaraciones conversacionales.
El formato plano coincide con el almacenamiento actual de la integración Meta.
Solo se reconocen alias comerciales expresos; no se interpretan etiquetas arbitrarias
como instrucciones ni se deducen características demográficas.

| Información | Tratamiento |
|---|---|
| Presupuesto, dormitorios, financiación, plazos e interés | Se conservan valor, fuente, evidencia disponible, fecha y referencia de origen |
| `unknown` | Dato desconocido, sin valor inventado |
| `declared` | Declaración del lead o formulario; no prueba de solvencia ni consentimiento |
| `confirmed` | Hecho marcado por una fuente de verificación administrativa; no se hereda del `confirmed=True` de una extracción LLM antigua |
| `declined` | Negativa a responder; se respeta y no se repite la misma pregunta |
| Corrección conversacional | Sustituye la preferencia anterior con `supersedes`; conserva evidencia histórica |
| Conflicto entre fuentes importadas | Queda diagnosticado y desconocido, sin elegir arbitrariamente una respuesta |
| Datos personales/protegidos y credenciales del formulario | No se incluyen en el perfil comercial enviado al modelo |

El primer nombre almacenado del lead se incorpora como identidad de referencia,
sin teléfono, correo ni inferencia de género. Las fechas de formularios preexistentes
usan la fecha disponible del registro del lead; no se afirma disponer de un timestamp
de respuesta Meta que no fue exportado. Un timestamp ausente permanece desconocido.
Las preguntas comerciales personalizadas sin un alias reconocido siguen en su fuente
original; no se adivina su significado. El mapeo se amplía de forma explícita si se
incorporan nuevos formularios reales.

La captura conversacional valida el mensaje dentro de Company/Project/conversation/lead
y usa evidencia literal del mensaje actual, no el valor normalizado que proponga el
modelo. Excluye las declaraciones citadas o atribuidas claramente a un tercero.
Se preservan preferencias negativas. Un cambio posterior del formulario no pisa una
corrección expresada en el chat; los campos importados que no fueron corregidos sí
vuelven a leerse en cada turno.

La versión `sales-lead-profile/2.0` vive bajo `lead_profile_data.sales_profile`, sin
reescribir datos Meta ni migrar todos los perfiles de producción. Mantiene la compatibilidad
de los hechos comerciales y el resumen del lead. Su historial resumido conserva hasta
100 versiones anteriores; los mensajes y eventos auditados siguen siendo la evidencia
completa. La vista del modelo limita valores/evidencias a 600 caracteres, muestra tres
hechos históricos recientes e indica el truncamiento sin modificar el registro fuente.

En la cohorte nueva, la siguiente pregunta usa este perfil: un presupuesto Meta conocido
no vuelve a solicitarse. Una moneda sin importe no equivale a un presupuesto conocido.
El scoring se mantiene para reporting, pero ese camino ya no asigna automáticamente
una persona, buyer type o etapa mediante palabras sueltas del formulario/historial.
Las guías de segmento ya almacenadas siguen disponibles; no se borran ni se inventan.

## Paso 6 — Contexto de turno y visitas independientes

`turn_memory.build` construye `sales-turn-context/1.0` con:

- Identidad mínima y perfil con procedencia.
- Interés actual: Project, tipología y unidad del estado conversacional.
- Citas activas, pasadas y canceladas, consultadas por Company y **lead exacto**.
- Memoria estructurada de ocho turnos y temas respondidos, sin resumen LLM inventado.
- Hasta veinte tareas pendientes, todas las restricciones y sus referencias.
- Historial pertinente, limitado a veinte mensajes y 12.000 caracteres, excluyendo
  mensajes futuros o etiquetados como pertenecientes a otro lead.
- Propuestas de cambio con expiración y estado de vigencia.

El intérprete usa `sales-understanding-prompt/2.1` y añade el campo opcional
`appointment_query: active | past | cancelled | all | null`. Una pregunta explícita
por una cita se procesa como consulta, sin buscar disponibilidad, crear una nueva
reserva, liberar horarios ni activar Calendar. La lectura por ID desconocido devuelve
un resultado vacío. Si no existe una cita activa, la respuesta es:

> You have no active appointments.

No se generan hora, especialista, dirección o tipología ausentes. La información que sí
existe se devuelve desde los registros, con estado, fecha/hora, zona, dirección y nombre
del especialista si está disponible. Una dirección o asignación faltante se indica como
tal. Las políticas aprobadas de Company/Project siguen vigentes; una consulta no concede
permisos de escritura ni dispensa restricciones.

`AppointmentReadTool` acepta únicamente categoría, ID opcional y límite. Nunca toma
Company/lead de argumentos del modelo. Incluye reservas del mismo lead en otro proyecto
de su Company, para conservar una visita a A cuando el interés actual está en B. No
amplía el alcance por teléfono, contacto compartido o ID de otro tenant. Limita cada
escaneo a 200 registros y señala cobertura parcial; no afirma ausencia si esa inspección
quedó incompleta. La vista por turno incluye como máximo cinco registros por categoría.

### Referencias persistentes de la visita

La migración aditiva `20261108_sales_visit_context`, posterior a
`20261106_sales_dialogue`, añade a `meetings`:

| Campo nullable | Finalidad |
|---|---|
| `visit_property_type_id` | Tipología expresamente elegida al reservar |
| `visit_unit_id` | Unidad expresamente elegida al reservar |
| `visit_context` | Snapshot de los nombres aprobados y zona horaria de esa visita |

`project_id` ya identifica el proyecto reservado. Las columnas existentes de dirección y
etiqueta de visita conservan su ubicación. No se rellena ninguna asociación histórica
usando la selección actual del lead, coincidencias de nombres o datos inferidos.

Las nuevas ofertas de horario incluyen su Project/tipología/unidad/ubicación. Al confirmar
se usa la asociación de la **oferta original**, aunque después haya cambiado el interés.
Una oferta antigua sin esa asociación conserva la tipología/unidad como desconocida.
El servicio valida las referencias contra el catálogo/inventario aprobado. Como las unidades
actualmente tienen una tipología textual, no se crea una relación por similitud de nombres:
una pareja explícita unidad/tipología debe coincidir exactamente en los datos aprobados.
La normalización relacional del catálogo y la selección comercial avanzada no se anticipan.

Las APIs existentes aceptan referencias opcionales al crear una visita y las exponen al
consultarla. La validación sucede antes de llamar a Calendar. Los consumidores anteriores
pueden seguir omitiéndolas. No se añade un editor nuevo de citas en frontend.

La hora se devuelve desde el registro y se convierte con la zona de la reserva. En citas
legadas sin snapshot se identifica expresamente el fallback a la zona actual del proyecto;
una zona inválida se diagnostica y se devuelve UTC. No se afirma haber reconstruido la
zona histórica. Las referencias FK admiten `SET NULL` al eliminar una tipología/unidad,
conservando el snapshot que sí se guardó al reservar.

### Memoria y propuestas

`DialogueState` admite `selected_unit_id`, memoria y propuestas opcionales, conservando
la lectura de JSON histórico sin esos campos. Los eventos anteriores no se reescriben.
La memoria contiene IDs, fecha, temas, campos declarados y selección; los hechos completos
y restricciones conservan sus propios almacenes de evidencia. El modelo recibe una
proyección del estado para evitar duplicar toda la auditoría dentro del contexto.
Se actualiza después de la aceptación del proveedor, sin confundirla con entrega real.
Un envío fallido no se resume como respondido; el reintento registra el turno una sola vez.

El helper interno `turn_memory.propose` guarda una propuesta con CAS e idempotencia,
snapshot hash de la reserva, destino validado y vencimiento de hasta treinta minutos.
No comprueba disponibilidad ni reserva el nuevo slot; expone `availability=not_checked`
y `authorizes_change=false`. El cambio de la reserva invalida la propuesta. Si se revoca
el destino, queda diagnosticado y la conversación puede seguir. Las propuestas vencidas
no autorizan nada y su eliminación de la vista actual no borra los eventos anteriores.

No se implementa todavía el diálogo de confirmación ni la sustitución/cancelación de la
reserva: pertenecen a F/G/H. La reactivación tras una pausa histórica por cita corresponde
al grupo I. C no levanta controles manuales, consentimientos ni pausas de producción.
La generación comercial natural del compositor final sigue pendiente de E.

## Aplicación y pruebas

Se mantienen las variables de cohorte de B, desactivadas por defecto. No se publican
prompts ni se cambia el modelo `openai/gpt-4o-mini` registrado en el snapshot. El código
necesita su migración **antes de arrancar la nueva versión**; el workflow existente de
despliegue ejecuta Alembic después de su preflight. No hace falta ejecutar SQL manual.
Fuera de ese workflow, aplicar la migración en el procedimiento habitual del entorno
antes de iniciar API/worker. No se ejecutó ninguna migración en producción en esta entrega.

```bash
cd backend
BP_PYTHON=python bash tools/sales_ai/offline.sh group-c
BP_PYTHON=python bash tools/sales_ai/offline.sh group-b
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-a-replay.json
```

Las pruebas nuevas cubren el presupuesto Meta, correcciones, negativas, conflictos,
aislamiento de datos, consultas de citas, cambio de interés sin cambiar reserva,
reserva real del coordinador con referencias de la oferta original, memoria acotada,
propuestas vencidas/stale/revocadas y migración reversible sin backfill. También incluyen
las seis propiedades exportadas, en SMS y WhatsApp, con presupuesto Meta **sintético**
identificado. No hay respuestas comerciales Meta reales nuevas que acreditar con ese fixture.

Se verifica PostgreSQL mediante generación del SQL de upgrade, sin conexión a una base
real. SQLite se comprueba con registros históricos y adjuntos, con FK activadas: se
añaden columnas sin recrear `meetings`, para preservar esos adjuntos. La reversión local
usa `DROP COLUMN` de las versiones modernas de SQLite del entorno de pruebas.

Docker no está disponible aquí. La suite se ejecuta además en una copia física aislada
de los `COPY` y montajes de Actions. El build real de la imagen, el modelo OpenRouter,
Calendar y los canales reales no se han ejecutado. Las pruebas de concurrencia PostgreSQL
siguen requiriendo una base desechable explícita. T01–T26 no se dan por aceptados end to end.
