# Sales AI — Grupo H: paso 14

Fecha: 8 de noviembre de 2026. Base de main con G: `95c062dea640033300f559544c2649417bce5851`.
Rama: `sales-ai/group-h-cancellation`. Continúa A–G. Siguiente: **I, paso 15**, pendiente.
Resultados reproducibles y límites: `group-h-report.json`.

## Cancelación confirmada

El motor `sales-cancellation/1.0` consulta las visitas futuras activas del mismo lead y Company.
Si existe más de una, pide elegir la cita mediante una lista del backend. No la identifica por
el interés comercial actual. Las visitas en curso, pasadas, completadas o ya canceladas no se
cancelan por este recorrido; requieren el tratamiento operativo correspondiente.

Una solicitud explícita muestra proyecto, propiedad/unidad registrada, especialista, fecha,
hora/zona/offset, duración y dirección de la visita y pregunta si debe cancelar **esa cita exacta**.
El horario sigue reservado. Sólo la aceptación contextual del resumen actual, enviado completo
y aceptado por el proveedor, puede cancelar. La propuesta vincula ámbito, contenido, versión de
la cita y vencimiento de 30 minutos mediante un identificador derivado del contenido completo.
Un resumen antiguo, alterado, vencido, interrumpido por otra oferta o seguido de una respuesta
manual no autoriza cancelar. Tampoco lo hacen elegir otra propiedad, despedirse o decir que no
hay más dudas. Una negativa al resumen conserva la reserva; no se convierte en baja del canal.

La aceptación bloquea el lead, el recibo de reserva y la cita; comprueba propietario, Company,
estado, hora futura, versión y políticas actuales de origen y proyecto reservado. También
bloquea el especialista al liberar el horario. Guarda la cancelación, su recibo y el aviso del
panel en la misma transacción. Un fallo de persistencia revierte todos esos cambios, sin liberar
la cita a medias. Una validación adicional de permisos tras componer la respuesta protege el
commit. Las claves únicas por propuesta y Meeting y la respuesta preparada evitan repetir la
cancelación o sus efectos al reintentar el mismo envío.

La cita queda `cancelled` con `confirmation_status=cancelled_by_lead`; no se borra. El horario
local deja de bloquear nuevas reservas al commit. Un evento externo aún pendiente de eliminar
puede seguir bloqueando el Calendar hasta su recuperación: no se afirma liberación externa antes
de completarla. No se modifica el cursor de reparto ni se cambia el especialista del lead.
Si no quedan otras visitas activas, se retira el estado operativo de cita confirmada sin cambiar
un resultado de venta cerrado. La conversación sigue abierta y la cadencia comercial detenida.

Cancelar una cita existente no exige que su propiedad siga vendible o aprobada en el catálogo.
La operación sí respeta el ámbito, las restricciones aprobadas y los interruptores/allowlists del
proyecto de origen y del reservado. No mueve la conversación ni la oportunidad a otro Project.
Las reservas históricas sin tipología/unidad conservan esa asociación desconocida.

## Motivo opcional y continuidad

La confirmación pregunta una sola vez por el motivo, de manera explícitamente opcional y después
de guardar la cancelación. Si el lead ya indicó voluntariamente un motivo al solicitarla, lo
conserva con el mensaje de origen y no vuelve a preguntarlo. Una respuesta voluntaria al mensaje
actual se guarda en el recibo; una negativa no impide cancelar, no produce baja ni otra cita.
Una respuesta posterior sin esa pregunta actual no se agrega como motivo por una referencia vieja.

El lead puede seguir preguntando por otra propiedad. La cadencia detenida por cancelación evita
invitaciones comerciales de agenda no solicitadas. Para una nueva visita debe existir una nueva
solicitud explícita; sigue siendo necesario elegir un horario y aceptar su resumen completo de F.
Un “yes” a la pregunta sobre el motivo no reserva. Una confirmación mezclada con una petición de
material conserva el hecho de la cancelación y una sola pregunta. Si el resumen de cancelación
no se muestra porque se priorizó otra oferta, aceptar esa oferta no cancela la visita.

Contrato interno: `sales-understanding-prompt/2.5`, con `cancellation` y evidencia exacta.
Los registros anteriores siguen cargando por defecto. No se publica un prompt administrativo
ni se cambia el modelo configurado. El simulador anterior no representa esta ruta de producción.

## Efectos durables y recuperación

Nueva revisión **`20261108_sales_cancel_ops`**, posterior a `20261108_sales_reschedule_ops`.
Crea solamente `sales_cancellation_operations`, con snapshots, estado/intentos/errores y fechas
para Calendar y avisos, además del motivo opcional y su mensaje. No reescribe Meetings ni altera
el esquema de los outboxes existentes. Debe aplicarse antes de iniciar API/worker con este código.

Después del commit se retira únicamente el evento conocido de la cita cancelada. Para una
creación F que se intentó pero pudo agotar el tiempo antes de guardar su ID, se usa el ID
determinista de esa misma reserva. La eliminación comprueba Meeting, Company, lead, especialista,
conexión y calendario guardados; una vinculación distinta queda en revisión, sin borrar otro
objeto. El cliente reconoce 404/410 como evento ya inexistente al repetir DELETE; los errores de
permisos y de servidor siguen siendo fallos recuperables. Referencia del proveedor:
https://developers.google.com/workspace/calendar/api/guides/errors#410_gone.
Una conexión desconectada espera que se recupere la misma conexión.

Cuando la cita procede de una reprogramación G con retiro antiguo pendiente, el recibo H toma
la limpieza de esos ancestros y detiene los recibos G correspondientes. Sigue como máximo diez
reprogramaciones; una cadena mayor queda en revisión y exige reconciliación manual. Los objetivos
ya completados no se repiten. Esto evita dejar un evento antiguo porque el último reemplazo ya
se canceló. Los workers F/G no vuelven a crear la reserva cancelada.

Los errores externos quedan con su tipo, presupuesto y siguiente intento. Calendar reintenta
con backoff, hasta cinco pasadas con intentos antes de revisión; una pasada puede revisar varios
objetivos de una cadena, conservando el progreso. El worker existente recupera operaciones
pendientes en lotes acotados y comprueba los ámbitos habilitados antes de eliminar eventos.
No crea Meetings ni se envía un mensaje al lead desde ese worker.

El aviso del panel se dirige al Sales de la visita, con deduplicación y destinatario explícito,
aunque el lead se reasigne. Sin especialista registrado se dirige a responsables de la Company.
Su procesamiento usa un savepoint independiente: un fallo no deshace la cancelación ya guardada,
queda visible en el recibo y se reintenta con backoff hasta cinco intentos, luego revisión.
Los avisos antiguos sin recibo H conservan su recorrido anterior. Los avisos procesados no se
repiten. No se afirma envío de correo separado, entrega al teléfono o éxito externo sin recibo.

Los responsables con rol Administrator/Assistant pueden consultar y reponer el presupuesto de
un efecto fallido con los endpoints del router de governance:

- `GET /appointment-cancellations/{operation_id}/effects`
- `POST /appointment-cancellations/{operation_id}/effects/retry`

Ambos se montan bajo el prefijo de governance existente y validan Company y acceso a todos los
Projects del recibo. Devuelven estado, intentos, tipo del error y próxima fecha de recuperación.
El POST sólo restablece efectos pendientes, nunca cancela ni reserva otra vez; no cambia una
vinculación Calendar. Una cadena por encima del límite requiere revisión manual y no se reinicia
por ese endpoint. No se añade una pantalla nueva: la visibilidad general del agente sigue en J.
Los avisos del panel ya autorizados usan su outbox existente; los interruptores de Calendar no
se presentan como cancelación de esos avisos persistidos.

## Verificación y aplicación

```bash
cd backend
alembic upgrade head
BP_PYTHON=python bash tools/sales_ai/offline.sh group-h
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-h-replay.json
```

Las 54 pruebas enfocadas usan coordinador, persistencia y despachador reales con interpretación
y proveedores simulados. Cubren confirmación en SMS/WhatsApp, negativas, despedidas, vencimiento,
cambios de cita, aislamiento, varias visitas, material mixto, motivo opcional, fallo de envío,
rollback, liberación local de horario, reprogramaciones previas, Calendar, avisos, recuperación
operativa y migración SQLite/DDL PostgreSQL. El informe distingue esta evidencia de la aceptación
real con el modelo/canales y de las pruebas paralelas en PostgreSQL.

No se ejecutaron modelo, mensajería o Calendar reales ni concurrencia real en PostgreSQL.
Los cuatro tests PostgreSQL heredados se omiten sin una URL de base desechable. No se ejecutó
Docker, un workflow remoto, despliegue ni migración productiva. Las copias físicas aisladas del
layout de Actions no equivalen a construir una imagen. La aceptación integral T01–T26 permanece
pendiente en K/L. El grupo I (espera y alternativas) no está implementado en esta entrega.

Los interruptores del nuevo flujo siguen desactivados por defecto. Para rollback operativo,
detener la cohorte, conservar citas, recibos y eventos, y reconciliar los efectos pendientes.
No usar un downgrade destructivo como reversión de código ni reactivar una imagen con lector
JSON estricto incompatible con los campos nuevos. Desactivar el flujo no deshace cancelaciones
ya confirmadas. No se han cambiado frontend, modelo o configuración productiva.
