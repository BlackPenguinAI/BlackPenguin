# Sales AI — Grupo F: pasos 11 y 12

Fecha: 8 de noviembre de 2026. Base de main con E: `f92e8046cf09c253da78b9636c311c7dfed62988`.
Rama: `sales-ai/group-f-booking-continuity`. Continúa A–E. Siguiente: **G, paso 13**, pendiente.
Resultados reproducibles: `group-f-report.json`.

## Paso 11 — Primera reserva y confirmación

La cohorte nueva usa `sales-first-booking/1.0`. Conserva consultas de citas de C y el flujo
anterior fuera de la allowlist. El recorrido tiene tres mensajes del backend:

1. Ofrece hasta tres horarios verificados para una propiedad/unidad y ubicación concretas,
   duración y especialista elegible. Si hay varias propiedades o ubicaciones, pide la elección
   pertinente sin exigir presupuesto ni completar todas las etapas comerciales.
2. Al elegir un horario, prepara un resumen completo y pregunta si debe reservar **esa visita
   exacta**. Elegir un número o una hora no crea una reserva. La propuesta conserva el mensaje
   de origen, su ámbito, datos y vencimiento original; tiene un identificador derivado del
   contenido completo. Una interrupción no prolonga los 30 minutos originales.
3. La aceptación contextual de ese resumen revalida permisos, referencia, fecha futura,
   propiedad, ubicación, especialista y disponibilidad. Guarda cita, asignación, recibo de
   operación y aviso en la misma transacción. La confirmación usa los valores guardados e
   incluye propiedad/unidad, especialista, fecha, hora/zona/offset, duración, dirección y un
   cierre útil. Se envía por el canal activo SMS/WhatsApp, sin afirmar entrega al teléfono.

Las referencias a un horario suspendido pueden preparar el resumen si son explícitas, la oferta
original fue aceptada por el proveedor y sigue vigente. Las ofertas multipartes deben estar
completas. Una pregunta o respuesta manual posterior no autoriza aceptar un resumen antiguo.
Las selecciones de propiedad siguen siendo independientes del consentimiento de reserva.
Una pregunta sobre fotos o precios interrumpe la agenda sin convertirse en solicitud de horarios.

### Preferencias y disponibilidad

El contrato de interpretación interno pasa a `sales-understanding-prompt/2.3`. Añade `visit`
(acción y fragmentos temporales exactos) y `courtesy` (saludo, agradecimiento, despedida o negativa).
Los registros históricos omiten estos campos y siguen cargando mediante valores predeterminados.
No se publica un prompt administrativo ni se cambia el modelo configurado.

El backend normaliza evidencia temporal explícita en fechas/rangos, hora local exacta o límites,
franjas del día, zona IANA y duración. Conserva los valores y su evidencia en `booking_search`.
No acepta fechas, zonas ni duraciones inventadas en lugar de fragmentos del mensaje. La duración
predeterminada es 45 minutos; una duración explícita debe estar entre 15 y 180 minutos.
La zona del Project es el valor predeterminado; una zona explícita válida se convierte a UTC para
reservar y se muestra en el resumen. Un valor ambiguo o inválido produce una aclaración inglesa.

La búsqueda usa una sola exploración de disponibilidad y un rango FreeBusy por especialista
conectado, sin repetirlo por cada día. Comprueba hasta 14 días dentro del rango solicitado,
retorna hasta tres opciones y comunica ese límite si no encuentra un horario. Acepta solicitudes
hasta 90 días en el futuro y rangos de hasta 31 días; no presenta la revisión de 14 días como
cobertura de un rango mayor. No registra espera ni promete avisos futuros: corresponden a I.
El tiempo real de búsqueda con proveedores externos sigue sujeto a sus timeouts y se evaluará en K;
no se atribuye a esta búsqueda el presupuesto separado de lecturas del plan de D.

La propuesta conserva el especialista mostrado. La confirmación no lo sustituye silenciosamente
por otro si cambió el cursor round robin. La asignación definitiva actualiza el cursor existente.
Una cita en curso también bloquea horarios solapados. No se confunde una consulta de inventario,
una imagen o una despedida con una autorización de agenda.

### Transacción y efectos durables

Nueva migración: **`20261108_sales_booking_ops`**, archivo
`backend/alembic/versions/20261108_sales_booking_operations.py`, posterior a
`20261108_sales_visit_context`. Crea solamente `sales_booking_operations`; no reescribe ni
reconstruye reservas históricas. El recibo tiene claves únicas por propuesta y Meeting, ámbito,
snapshot de confirmación y estado/intentos del efecto Calendar.

Se bloquea el lead antes de comprobar otra reserva activa y se conservan los bloqueos de Sales
ordenados antes de comprobar conflictos. Esto coordina dos canales del mismo lead y dos leads
que compiten por un especialista. Los tests secuenciales verifican conflictos, y se añaden tests
paralelos reales optativos para PostgreSQL. **SQLite no acredita concurrencia PostgreSQL**; las
pruebas omitidas y el nivel de evidencia se declaran en el informe.

La respuesta preparada y sus operaciones persisten antes del envío. Reintentar un envío fallido
reutiliza esa respuesta y esa reserva; un nuevo “yes” posterior tampoco crea otra cita si existe
una activa. Cambiar el interés no modifica la propiedad reservada. Reprogramar y cancelar no se
ejecutan mediante esta ruta de primera reserva: conservan G y H.

Los avisos usan `NotificationOutbox`, con deduplicación por Meeting y destinatario. El Sales de
ese aviso es el de la reserva, aunque el lead se reasigne antes de procesar el outbox. Son avisos
del panel existente; esta entrega no afirma haber enviado un correo separado de confirmación.

Calendar se ejecuta después del commit y tiene ID de evento determinista por Meeting. El worker
existente revisa los recibos pendientes; un fallo no borra la reserva. Los intentos fallidos se
reintentan con backoff, hasta cinco llamadas por operación antes de dejar `review`. Sin conexión,
queda `waiting_connection` con revisión a los diez minutos. Un cambio de fecha/hora, especialista, duración o dirección de la reserva deja
la operación en revisión en lugar de sincronizar datos distintos a los confirmados. No se crea
un nuevo Meeting al recuperar un fallo externo. Los eventos simulados no llaman al proveedor.
La política de cohortes/interruptores sigue limitando los reintentos automáticos.

## Paso 12 — Conversación abierta y cadencia separada

Reservar deja `conversation.is_paused=False`; `cadence_status=stopped` con motivo `booked`
detiene los seguimientos comerciales. Una despedida detiene la cadencia con motivo `farewell`,
sin dar de baja al lead, cancelar visitas ni impedir consultas nuevas. Un saludo al regresar
puede recibir una bienvenida. Las consultas posteriores usan el lector de citas existente y
sus snapshots, sin reinterpretar el interés actual como una reserva distinta.

El control se aplica al ingreso de webhooks, al coordinador y a los trabajos de seguimiento.
La pausa histórica exacta `Appointment confirmed` se puede recuperar en la cohorte autorizada
cuando hay una reserva del ámbito y no hay baja ni intervención humana abierta. Las pausas
manuales, de seguridad, legales o de intervención no se levantan por este mecanismo. La
recuperación registra un evento; no cambia la cita ni completa asociaciones históricas desconocidas.

Una negativa breve al resumen declina la propuesta; una negativa breve a la pregunta posterior
a la confirmación responde a esa pregunta. Se protege esa interpretación incluso ante una
etiqueta errónea del modelo que intente convertir “No” en baja o reserva. Los controles explícitos
de consentimiento y las palabras de opt-out del canal conservan su prioridad. Una despedida no
los sustituye ni elimina restricciones previas.

Una confirmación combinada con una solicitud de material conserva los datos de la reserva y
una sola pregunta útil. Si el material relacionado necesita aceptación, se retira la pregunta
opcional de cierre de la cita, no la confirmación verdadera. No se afirma que una reserva ya
guardada siga pendiente.

## Verificación, aplicación y límites

```bash
cd backend
BP_PYTHON=python bash tools/sales_ai/offline.sh group-f
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-f-replay.json
```

El wrapper offline deja vacía la URL PostgreSQL intencionalmente. Los tests
`tests/test_sales_booking_postgres.py` se pueden ejecutar directamente en un entorno de pruebas
con `DIALOGUE_POSTGRES_TEST_URL` explícita. Rechazan bases cuyo nombre no termine en `_test` y
crean/eliminan solo un esquema aleatorio propio. No se ejecutaron contra producción.

Se prueban coordinador, persistencia, ingreso y despachador reales, con modelo/proveedores
simulados: reserva en dos pasos, reintento, postreserva, cambio de interés, despedida/regreso,
“No” contextual, negativas, referencias, preferencias, zonas, duración, varias ubicaciones,
materiales mixtos, conflictos, notificaciones, fallos/recuperación de Calendar y migración SQLite.
Se genera también el DDL de la migración para PostgreSQL. Los seis proyectos exportados se usan
para solicitudes de visita y aislamiento en ambos canales, sin inventar disponibilidad faltante;
esto no equivale a completar una reserva real en cada proyecto.

Antes de arrancar API/worker con este código se requiere `alembic upgrade head`. Aplicar archivos
sin migrar no acredita un despliegue válido. Se mantienen apagados por defecto los interruptores
de la cohorte nueva; no se cambia configuración de producción, frontend ni modelo. El simulador
anterior no representa esta ruta.

Para revertir código tras haber activado F, detener primero la automatización de la cohorte y
revisar turnos preparados/efectos pendientes. Conservar la tabla, los Meetings, eventos y snapshots;
no ejecutar un downgrade que borre recibos pendientes como procedimiento de rollback operativo.
El esquema JSON nuevo necesita un lector compatible; no exponer esos estados a una imagen antigua
con contrato estricto sin una estrategia de compatibilidad. Reconciliar Calendar y avisos antes
de reactivar otra versión. Desactivar automatización no cancela las citas guardadas.

No se ejecutaron modelo real, Calendar/mensajería real ni aceptación completa T01–T26. La calidad
comercial, las carreras reales de PostgreSQL y las pruebas con canales autorizados mantienen sus
niveles pendientes. Docker no está instalado: la disposición de Actions se verifica por copias
físicas aisladas, sin afirmar una construcción de imagen, workflow remoto o despliegue.
