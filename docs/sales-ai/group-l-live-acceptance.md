# Grupo L — Prueba real controlada

Estado inicial: **NOT_RUN**. No existe aquí una autorización identificada con entorno y contacto
exacto; tampoco están cerrados los requisitos externos de K. Este documento prepara la ejecución
del operador. No envía mensajes ni habilita autonomía y no autoriza usar contactos históricos.

## Preparación obligatoria del ensayo

1. Cerrar K sobre la revisión candidata: modelo real y repeticiones, revisión comercial humana,
   PostgreSQL concurrente y recorrido visual escritorio/móvil. Registrar fallos y corregirlos antes
   de pasar al canal real. Mantener separados los escenarios sintéticos y los de datos exportados.
2. Identificar entorno, Company/Project/lead de prueba y operador. Registrar número exacto y titular,
   consentimiento para SMS y WhatsApp, remitente/proveedor, ventana temporal y alcance autorizado.
   Si falta cualquiera de esos datos, no iniciar el envío ni elegir un teléfono existente del CRM.
3. Confirmar presupuesto/límites del modelo, configuración publicada, rol/permisos, materiales de
   prueba autorizados y Sales/Calendar del laboratorio. No desconectar integraciones de clientes
   ni provocar fallos en cuentas ajenas para simular incidencias.
4. Comparar SHA de API, worker y frontend; guardar los audit/export del ámbito. Anotar head de
   Alembic y versión/hash de configuración. Respaldar datos/archivos y demostrar recuperación
   en un destino aislado. Preparar reversión al lector compatible con los mismos estados/recibos.
5. Delimitar la cohorte al lead de prueba. En WhatsApp abrir la ventana de atención con un mensaje
   real del tester; si se requiere plantilla fuera de ventana, usar sólo una aprobada y autorizada.
   No inventar una plantilla ni cambiar de canal como alternativa automática.

## Recorrido, repetido en SMS y WhatsApp

Usar nombres/horarios reales aprobados del proyecto de prueba; los textos entre corchetes son
variables, no hechos que deban copiarse literalmente. Hacer primero un canal y cancelar/conciliar
su cita antes del segundo para no confundir reservas existentes entre conversaciones del mismo lead.

| Paso | Acción del tester u operador | Evidencia necesaria |
|---|---|---|
| 1 | Iniciar desde el teléfono autorizado: “Hello”, luego “Give me information”. | Webhook autenticado, mensaje y job únicos, AgentRun correcto y respuesta comercial recibida en el teléfono. |
| 2 | Elegir `[propiedad A]`, solicitar material aprobado y preguntar financiación. | IDs/cobertura de material, respuesta completa, enlace accesible con sus reglas; el PDF/foto realmente contiene lo anunciado. |
| 3 | Pedir visita, elegir opción vigente y confirmar el resumen exacto. | Un Meeting con propiedad/unidad/lugar/Sales/fecha/duración/TZ correctos, una operación y recibo; evento real en Calendar y aviso real a Sales. |
| 4 | Preguntar “When is my appointment?”, consultar `[propiedad B]`, despedirse y volver. | Se responde con la cita A persistida; consultar B no modifica A y despedirse no da de baja ni cierra permanentemente el chat. |
| 5 | Solicitar cambio, comparar y rechazar primero. Después pedirlo otra vez y confirmar. | Rechazo conserva A; confirmación crea un único reemplazo. Se verifica el nuevo evento antes de retirar el anterior; avisos al Sales correcto y confirmación recibida por el canal original. |
| 6 | Cancelar y confirmar el resumen exacto. Volver a consultar una propiedad. | Cita cancelada una vez, evento real retirado, outbox/aviso comprobados y conversación abierta. No se crea otra reserva por preguntar. |
| 7 | Si se prueba disponibilidad, solicitar expresamente un aviso y habilitar un horario de laboratorio. | Solicitud persistida antes de prometer contacto, preferencias/ventana correctas y un aviso comprobable; el aviso no reserva sin selección y confirmación. |
| 8 | Tomar control manual, enviar una respuesta y reanudar según permisos. Probar revisión acotada de un caso sintético del ensayo. | Mensaje humano recibido, resolución auditada, motivo/evidencia visibles y estado coherente en Agent/Schedule/Monitor. |
| 9 | Sólo al terminar ambos canales, comprobar la baja explícita y que una revisión no permite reanudarla. | Consentimiento/baja persistidos, futuros contactos bloqueados. No restaurar consentimiento sólo para seguir el ensayo. |

`sent`/`accepted` prueba aceptación por el proveedor, no entrega al dispositivo. Conservar recibo
terminal autenticado cuando esté disponible y comprobación en el teléfono de prueba. SMS no requiere
un recibo de lectura inexistente. Exportar IDs/estados y referencias redactadas; no copiar claves,
tokens, números privados o payloads sin redacción al repositorio/ZIP público.

## Fallos y reconciliación

- Si hay un timeout con resultado incierto, detener el ensayo y revisar los IDs/recibos del proveedor
  antes de repetir. No dar por seguro que un error de red significa que el mensaje no salió.
- Probar duplicados/reintentos con callbacks o herramientas del entorno de laboratorio; la prueba
  offline de una firma/cola no se presenta como una entrega real. Las incidencias deben quedar
  diagnosticables y sin segunda reserva, segundo reemplazo o aviso duplicado.
- Revisar cada Meeting y operación en DB, cada evento en Calendar y cada aviso a Sales. El texto de
  confirmación, un outbox `pending` o un healthcheck verde no reemplazan esos efectos reales.
- El operador marca cada entrada del checklist sólo después de revisar su evidencia sobre el SHA
  candidato. Cualquier caso crítico fallido mantiene bloqueada la publicación.

Al finalizar, documentar cleanup explícito de citas/eventos de prueba y estado final de la cohorte,
sin borrar trazas ni restaurar consentimientos retirados. El registro de autorización y evidencias
privadas se conserva con sus permisos adecuados, separado del entregable de código.
