# Sales AI — Grupo G: paso 13

Fecha: 8 de noviembre de 2026. Base de main con F: `c2355a71362169f25e1f01471888e5a8c9259b75`.
Rama: `sales-ai/group-g-reschedule`. Continúa A–F. Siguiente: **H, paso 14**, pendiente.
Resultados y límites: `group-g-report.json`.

## Reprogramación explícita

El motor `sales-reschedule/1.0` identifica una visita futura activa del lead. Si hay varias,
pide elegir una mediante una lista del backend; no deduce la cita desde el interés comercial.
Conserva por defecto la propiedad, unidad, ubicación y duración de la reserva original y
normaliza las preferencias temporales mediante el motor de F. Admite cambios explícitos de
propiedad, unidad, ubicación, Project o especialista elegible, con nombres respaldados por el
catálogo y fragmentos exactos del mensaje. El contrato interno pasa a
`sales-understanding-prompt/2.4`; no publica prompts administrativos ni cambia el modelo.

El recorrido es: solicitud → opciones verificadas → selección → comparación completa entre
cita actual y propuesta → aceptación de esa comparación → sustitución. Elegir un horario no
reemplaza la cita. El resumen incluye proyecto, propiedad/unidad, especialista, fecha, hora,
zona/offset, duración y dirección. La propuesta está vinculada a su ámbito, datos completos,
versión de la cita original y vencimiento de 30 minutos; seleccionar después no extiende ese
plazo. Las respuestas breves sólo aceptan una comparación vigente enviada completamente y
aceptada por el proveedor. Una respuesta manual, un envío incompleto, una interrupción sobre
material o un resumen antiguo no autoriza un cambio. Un “No” contextual conserva la cita.

Un cambio de Project comprueba pertenencia a la misma Company, aprobación, capacidad de citas,
allowlist de activación, política de ejecución, restricciones aprobadas y equipo del destino.
No mueve implícitamente la conversación ni la oportunidad del lead a otro Project. La nueva
visita guarda el destino solicitado, manteniendo el mismo lead y el ámbito autorizado de origen.

## Sustitución atómica

Al aceptar, el backend bloquea el lead, el recibo anterior, la cita original y los especialistas
relevantes en orden estable; revalida el snapshot, permisos, catálogo, ubicación, hora futura,
especialista elegido y disponibilidad. La comprobación excluye únicamente la cita original.
Si existe un evento Google, se enumeran instancias para excluir únicamente su ID conocido;
no se resta un intervalo de FreeBusy que pudiera ocultar otros eventos solapados. Errores,
datos incompletos o paginación excesiva bloquean el rango. Los eventos de día completo se
convierten con su zona correspondiente. La búsqueda conserva los límites temporales de F.

En un savepoint crea la nueva reserva confirmada, su recibo F, un recibo de reprogramación y
los avisos; sólo entonces marca la anterior `cancelled` con `confirmation_status=rescheduled`.
El historial la muestra como reemplazada. Un conflicto conserva la reserva original, el cursor
de asignación y el lead. Un fallo posterior revierte la transacción completa. Tras componer
la respuesta se comprueban otra vez permisos y contexto del destino antes del commit.
Las claves únicas por propuesta, cita original y reemplazo impiden duplicar operaciones.
No se presenta esta evidencia SQLite como prueba de carreras reales en PostgreSQL.

La confirmación sale por el canal activo SMS/WhatsApp, con datos guardados y una sola pregunta
útil aun si el mismo mensaje solicita material. La conversación permanece abierta y la cadencia
comercial detenida. Un reintento de envío usa la respuesta preparada, sin volver a reservar.

## Calendar y avisos

La nueva tabla `sales_reschedule_operations` conserva el ámbito, snapshots y el progreso de
retiro del evento anterior. Después del commit crea el evento nuevo mediante el recibo F y
su ID determinista; sólo después de sincronizarlo retira el ID exacto del evento anterior.
Comprueba propietario, conexión, calendario y estado de la cita. Un fallo de creación conserva
el evento anterior. Un fallo de eliminación se reintenta con backoff hasta cinco intentos y
luego queda en revisión. Sin conexión espera; un cambio de vinculación exige revisión.
Los cambios sucesivos pueden seguir una cadena acotada de recibos para retirar eventos viejos
cuando el reemplazo definitivo está sincronizado. El worker no crea Meetings nuevos.
Los interruptores y allowlists de origen y destino limitan los efectos automáticos.

Se encolan avisos del panel para el Sales anterior y el nuevo, con destinatario explícito y
clave de deduplicación. Una reasignación posterior del lead no desvía esos avisos. Si es el
mismo especialista recibe los dos avisos de rol correspondientes. No se afirma entrega de un
correo separado ni entrega al teléfono: el proveedor sólo acredita aceptación del envío.

## Aplicación y verificación

Nueva migración: **`20261108_sales_reschedule_ops`**, posterior a `20261108_sales_booking_ops`.
Crea solamente la tabla de recibos y su índice; no reescribe citas históricas. Aplicar con:

```bash
cd backend
alembic upgrade head
BP_PYTHON=python bash tools/sales_ai/offline.sh group-g
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-g-replay.json
```

Aplicar la migración antes de iniciar API/worker con estos archivos. Los interruptores del
nuevo flujo siguen desactivados por defecto; no se modificó configuración de producción.
El informe distingue pruebas enfocadas, regresión, replay y disposición aislada de Actions.
Se usan interpretación y proveedores simulados. Los casos de G cubren cambios de propiedad y
Project, rechazo, caducidad, permisos, elección de especialista, conflictos, rollback,
idempotencia, interrupciones, Calendar y migración SQLite/DDL PostgreSQL.

No se ejecutaron modelo real, Calendar/mensajería reales, concurrencia real PostgreSQL,
Docker, workflow remoto ni despliegue. Los cuatro tests PostgreSQL heredados se omiten cuando
no hay una URL de base desechable. La aceptación integral T01–T26 y esas pruebas mantienen
su evaluación pendiente en K/L; los tests de este grupo no equivalen a aceptación productiva.
Cancelación solicitada por el lead y espera durable siguen en H/I.

Para rollback operativo detener primero la cohorte y revisar respuestas preparadas y efectos.
Conservar citas, eventos y recibos; no borrar las tablas como mecanismo de reversión.
Los estados JSON con campos nuevos requieren un lector compatible antes de volver a una
imagen antigua con validación estricta. Reconciliar Calendar y avisos antes de reactivar.
Desactivar el flujo no revierte ni cancela las citas ya guardadas.
