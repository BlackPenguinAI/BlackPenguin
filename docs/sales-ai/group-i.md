# Sales AI — Grupo I: paso 15

Fecha: 8 de noviembre de 2026. Base de main con H: `b1b3ec29c504b3b0fd9c050836dc420c9ebe721d`.
Rama: `sales-ai/group-i-waitlist`. Continúa A–H. Siguiente: **J, pasos 16 y 17**, pendiente.
Resultados reproducibles y límites: `group-i-report.json`.

## Espera explícita y persistente

El motor `sales-availability-wait/1.0` ofrece guardar una solicitud cuando F/G no encuentran
un horario verificado. Presenta propiedad/proyecto, rango, zona y duración antes de pedir
aceptación. Una pregunta sobre un aviso no afirma que éste ya exista. Sólo una aceptación de
esa pregunta actual, completa y aceptada por el proveedor, o una solicitud explícita vinculada
al contexto verificado y vigente, guarda el registro. Un “yes” a material, una respuesta manual,
una propuesta caducada o una oferta oculta no lo autoriza. Un “No” contextual declina el aviso,
sin dar de baja el canal ni cancelar una cita.

La nueva tabla `sales_wait_requests` guarda Company, proyecto de origen y destino, conversación,
lead, mensaje del permiso, propiedad/unidad, ubicación, preferencias temporales, duración,
especialistas restringidos si los hubo, zona, interés de origen y visita original en caso de
reprogramación. También conserva canal/proveedor y una huella del contacto; un cambio no redirige
silenciosamente el aviso. El rango se fija en fechas, incluso cuando F usó sus catorce días
predeterminados. Caduca al terminar el último día solicitado en esa zona. Mantiene los límites
de F: inicio dentro de noventa días y rango de hasta treinta y un días.

Existe una sola espera activa por lead y Company, con clave única en base de datos. Una petición
idéntica reutiliza el registro; una nueva petición con contexto/canal/contacto distinto sustituye
explícitamente la anterior. No se afirma un aviso antes de guardar el registro en la misma
transacción que la respuesta preparada. Se comprueban otra vez los permisos después de componer
la respuesta. Un fallo de persistencia no deja una promesa de contacto sin registro.

El contrato interno pasa a `sales-understanding-prompt/2.6`, con `wait` y evidencia exacta para
solicitar, declinar, cancelar o consultar fechas cercanas. Se añaden sólo términos ingleses del
aviso al vocabulario breve de B, para admitir frases como “Cancel my alert request” sin confundir
su idioma. No se publica un prompt administrativo ni se cambia el modelo. Los lectores anteriores
con esquema estricto necesitan compatibilidad antes de recibir estos campos nuevos.

## Opciones cercanas y consentimiento de reserva

Las fechas cercanas requieren una petición explícita. Se consultan hasta tres días antes y tres
después del rango original, con un máximo de dos exploraciones; se devuelven hasta tres opciones
verificadas. Se mantienen propiedad/unidad, ubicación, duración, zona, horario del día y restricción
de especialista. Una modificación temporal explícita se normaliza desde su evidencia. No se
relajan las preferencias en silencio ni se agrega una espera por consultar alternativas.

La respuesta identifica que las fechas difieren del rango original. Elegir una opción sigue
preparando el resumen completo de F o la comparación completa de G; sólo una aceptación posterior
de esa propuesta exacta permite reservar/reemplazar. El worker de espera nunca crea Meetings.
En reprogramación se conserva la cita original al guardar, buscar, avisar, declinar o cerrar la
espera. G vuelve a validar la cita original al confirmar el reemplazo.

## Comprobación acotada y aviso único

El worker existente revisa solicitudes habilitadas en lotes de hasta diez, aproximadamente una
vez por minuto. Cada espera sin resultado vuelve a quedar disponible para comprobarse quince
minutos después. Cada comprobación explora hasta catorce días; un cursor durable rota por los
segmentos restantes de un rango mayor, sin limitarse siempre a las primeras dos semanas. Las
comprobaciones se mantienen dentro del horizonte vigente y vuelven al inicio útil al completar
el rango. Esto es un proceso periódico acotado, no un disparador inmediato ni una garantía de
latencia de un proveedor externo.

Se filtran Company/proyectos/leads autorizados y estados vencidos/diferidos antes de seleccionar
el lote. Se validan otra vez catálogo, ubicación, capacidades, políticas y elegibilidad del
especialista. Se comprueban consentimiento, control humano, pausa, contacto, interés, restricciones
persistidas y reserva original. Una nueva entrada pendiente de interpretar difiere el aviso:
no se envía usando el interés antiguo mientras otro turno aún puede cambiarlo.

La solicitud se reclama con bloqueo, arrendamiento de diez minutos y token por ejecución. Al
reiniciar puede recuperarse una reclamación vencida. Una ejecución sustituida no puede completar
el envío ni cambiar el estado del nuevo dueño. La notificación preparada conserva contenido,
opciones y vencimiento propios de treinta minutos; un reintento no los renueva.

El aviso usa el despachador existente y una clave estable por solicitud/parte. Antes de cada parte
y justo antes de intentar llamar al proveedor, se vuelven a comprobar ámbito, consentimiento,
interés, turno actual, canal, contenido exacto y disponibilidad. Los cambios bloquean el envío.
Los fragmentos ya aceptados se reutilizan; una entrega incompleta no permite aceptar una oferta
como si se hubiera mostrado completa. Se registra `notified` sólo con aceptación de todas las
partes por el proveedor; no equivale a entrega al teléfono.

Una respuesta explícita `failed` del proveedor puede reintentarse, con backoff y hasta tres
intentos de la notificación preparada. Un resultado sin confirmación, una excepción de red o una
salida incierta queda en `review`, sin reenvío automático que pudiera duplicar un aviso ya enviado.
Los errores/tipos y estados quedan en el registro. Una propuesta de aviso vencida o cuyos horarios
cambiaron deja de enviarse; no se reemplaza silenciosamente por un texto distinto con la misma
clave. Para otra solicitud se requiere un permiso nuevo del lead. La visibilidad general de estos
estados en una pantalla corresponde a J; esta entrega no añade frontend.

El aviso es de una sola vez por solicitud. Los controles de deduplicación, reclamación y la clave
del despachador se verifican con pruebas secuenciales y fallos simulados; no se presentan como
prueba ejecutada de concurrencia real PostgreSQL o de entrega exactamente una vez en una red
externa. El tratamiento conservador de resultados inciertos evita un reenvío automático a ciegas.

## Condiciones del canal y cierre

Se aplican las ventanas proactivas configuradas en los proyectos de origen y destino. WhatsApp
sólo usa texto libre dentro de su ventana de atención existente; fuera de ella se difiere la
solicitud hasta que exista una nueva entrada válida o venza. No se inventa una plantilla aprobada
ni se cambia a SMS para eludir la restricción. SMS conserva proveedor, destinatario y reglas
operativas guardadas. El permiso de aviso es independiente de la cadencia comercial de F/H.

La espera se cierra al reservar/reprogramar, al confirmar la cancelación de la visita, al cancelar
sólo el aviso, al cambiar el interés o las preferencias de la visita, al retirar consentimiento o cuando el rango termina. Los
cambios externos de permisos, propiedad o visita original también impiden continuar. Las entradas
procesadas reconcilian los cierres correspondientes; el proceso periódico y el último límite de
envío comprueban cambios realizados desde otros puntos. No se envía una alerta después de detectar
que ya no existe permiso de contacto. `notified` es un estado terminal: no provoca nuevos avisos
cuando vuelve a cambiar la disponibilidad. Cerrar una espera de reprogramación no libera la cita.

## Migración y verificación

Nueva revisión: **`20261108_sales_wait_requests`**, posterior a `20261108_sales_cancel_ops`.
Crea solamente la tabla de esperas y su índice, sin reescribir reservas ni outboxes existentes.
Aplicar antes de iniciar API/worker con este código:

```bash
cd backend
alembic upgrade head
BP_PYTHON=python bash tools/sales_ai/offline.sh group-i
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-i-replay.json
```

Las 47 pruebas enfocadas usan coordinador, persistencia, búsqueda y despachador reales con
interpretación/proveedores simulados. Incluyen SMS/WhatsApp, selección/confirmación posterior,
recuperación de reclamaciones/envíos, preferencias y fechas cercanas, rotación del rango, cierre,
reprogramación, fallos, control humano, baja, ventanas de contacto, revocación al último límite,
migración SQLite y DDL PostgreSQL. La regresión completa se ejecuta sobre una copia física aislada
del layout de Actions, con las referencias comprobadas sin modificaciones; no se duplica otra
regresión completa equivalente sólo para repetir el mismo resultado en el checkout.

No se ejecutaron modelo, Calendar o mensajería reales, concurrencia real PostgreSQL, Docker,
workflow remoto, despliegue ni migración productiva. Los cuatro tests PostgreSQL heredados se
omiten sin URL desechable. La aceptación integral T01–T26 y la calidad/latencia reales siguen
pendientes en K/L. Los interruptores y allowlists no cambian ni se activan con estos archivos.
La operación requiere el worker existente en funcionamiento al habilitar la cohorte.

Para rollback operativo detener la cohorte, conservar registros/citas/respuestas y revisar avisos
preparados o inciertos. No usar un downgrade destructivo ni una imagen con lector JSON incompatible.
Desactivar el worker no revierte reservas, cancelaciones o avisos aceptados. Mantener los cierres
y bajas al reconciliar solicitudes antes de reactivar otra versión.
