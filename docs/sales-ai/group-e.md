# Sales AI — Grupo E: pasos 9 y 10

Fecha: 8 de noviembre de 2026. Base de main: `da712a341e5e351f0f5d0c475d732e31101ea607`.
Rama: `sales-ai/group-e-response-materials`. Continúa A–D. Siguiente: **F, pasos 11 y 12**, pendiente.

## Paso 9 — Compositor comercial después de los resultados

La cohorte nueva llama al compositor después de interpretar y planificar, consultar datos,
normalizar el perfil y preparar los resultados autorizados. Recibe el perfil con su procedencia,
el interés actual separado de la visita reservada, memoria e historial acotados, restricciones,
resultados y playbook publicado: identidad, etapa, segmento y objeciones. Conserva el modelo
publicado y no modifica la configuración ni publica prompts.

El contrato `sales-commercial-composer/1.0` permite al LLM elegir apertura, orden, variantes de
redacción y una continuación permitida. **Las afirmaciones factuales proceden de bloques de
texto construidos por el backend**: el modelo no escribe cifras, URLs, hechos, beneficios ni
recibos libres. Todos los bloques necesarios para responder deben aparecer exactamente una vez;
los beneficios opcionales solo proceden de `value_proposition`/`key_differentiators` confirmados.
El catálogo mantiene su orden para que sus números sigan resolviendo a los mismos IDs.

Es una composición controlada mediante selección de redacción respaldada, no una paráfrasis
libre validada por otro LLM. Esta decisión hace ejecutable la validación de hechos y acciones,
a costa de limitar la variedad de expresión. La calidad comercial con el modelo real, incluida
la rúbrica 4/5 propuesta, se evaluará en K; no se considera medida ni aprobada aquí.

El cierre se elige entre opciones concretas autorizadas. No se apilan preguntas de catálogo,
presupuesto y material; los datos conocidos de Meta no se repreguntan. Una sola tipología se
explica con sus detalles aprobados, sin exigir una selección redundante. El único tipo también
puede servir de destino inequívoco de una consulta, sin convertirlo en interés declarado ni en
consentimiento de visita. Una invitación puede explicar la utilidad de evaluar la distribución
presencialmente; no crea una cita, no aparece si hay restricciones/una cita activa y no se repite
en el turno inmediatamente siguiente. Las etapas nunca son requisitos secuenciales.

Las aclaraciones y los límites del plan tienen prioridad. En solicitudes mixtas se presenta una
sola pregunta de aceptación; la necesidad de visita permanece pendiente si primero se pide
aceptar un material relacionado. Los permisos y el contexto aprobado se comprueban de nuevo tras
la inferencia. Un cambio de información aprobada invalida ese borrador, sin enviar sus datos antiguos.

### Límites y recuperación

- Una inferencia y, solo por contrato inválido, una reparación. Un error del proveedor no provoca
  otro intento de generación en ese turno.
- Presupuesto total de inferencia del compositor: 10 segundos; cada llamada tiene un máximo de
  8 segundos y 2048 tokens de salida. Máximo de contexto: 64 KB; contrato de respuesta: 16 KB y
  120 bloques. Los límites de interpretación y planificación de A–D son independientes.
- Si el modelo falla o el contexto excede el límite, se renderizan los bloques verificados y un
  cierre seguro. No se repiten herramientas ni se pausa por ese fallo.
- La nueva opción `max_tokens` del cliente OpenRouter es opcional; las llamadas existentes conservan
  su comportamiento. Se contabiliza el uso real bajo `sales_commercial_composition` cuando el proveedor
  reporta consumo. No se traduce un presupuesto de lecturas en un coste monetario inventado.
- Las URLs opacas de materiales se ocultan al compositor. El backend conserva los enlaces reales
  para renderizarlos y enviarlos. La traza conserva versión, modelo/configuración, selección del
  playbook, hashes, intentos, resultado y cierre elegido; no registra claves ni razonamiento privado.
- Un reintento de entrega reutiliza el borrador durable y los shares ya emitidos.

## Paso 10 — Materiales, alternativas y aceptación exacta

La búsqueda conserva el destino por ID de tipología, no solo su nombre. Una referencia a un
material concreto filtra la entrega a ese ID. Se aceptan referencias a una oferta actual como
“that file”, “the first file” o el nombre exacto; varias candidatas requieren aclaración.

Antes de considerar distribuible un archivo se verifica su existencia bajo la raíz permitida,
contenido no vacío, límite de 50 MiB, descifrado cuando corresponde y hash de integridad cuando
está registrado. Las fotos/tags y la cobertura siguen dependiendo de la revisión administrativa:
**leer bytes no demuestra que un PDF contenga fotos ni que cubra una unidad específica**.
Los PDFs sintéticos de pruebas tienen bytes locales identificados; no se presentan como archivos
comerciales reales de los proyectos exportados.

Las alternativas incluyen una propuesta expirable de 30 minutos con ámbito completo, IDs,
versión, fuente, nombre, tipo/tags, destino, hash de contenido y tareas originales. No se renueva
la expiración al responder ni se sustituye el archivo por otro descubierto después. La aceptación
requiere una oferta del asistente aceptada por el proveedor y completa si tiene varias partes.
Un mensaje manual, una oferta incompleta, una propuesta antigua o una pregunta competidora no
convierten un “yes” en autorización de envío.

Si faltan fotos, se ofrece un PDF relacionado accesible y aprobado, declarando que su cobertura
fotográfica no está confirmada. La cobertura de unidad desconocida también se explica. Si el
usuario lo acepta, se envía ese mismo recurso/version; un archivo nuevo, renombrado, modificado,
archivado, vencido o fuera del canal/propiedad no lo reemplaza silenciosamente. Las restricciones
de la propiedad original siguen aplicándose aunque el interés actual haya cambiado.

El backend emite las URLs. Revalida los bindings al preparar cada share, antes de despachar,
antes de cada parte y al abrir enlaces de esta nueva cohorte. También revalida recursos externos
contra la URL revisada y su esquema/host permitido; no hace peticiones de red para asegurar que un
servidor externo esté disponible. Un cambio invalida el enlace; no redirige a un archivo nuevo.
Las respuestas independientes verificadas, como financiación, se conservan cuando se retira un
enlace que cambió antes de enviarse.

Las necesidades materiales se completan tras el recibo durable de aceptación del proveedor, sin
confundirlo con entrega al teléfono ni con apertura humana. Al aceptar una alternativa relacionada,
la necesidad original se retira con motivo `accepted_related_alternative` después del recibo;
no se marca que se enviaron fotos inexistentes. Las solicitudes materiales independientes del
mismo turno conservan sus propios destinos y resultados. Los intentos fallidos no completan tareas.

Los enlaces anteriores conservan la compatibilidad del endpoint: la validación de bindings exactos
se aplica a los shares que llevan la nueva procedencia. Esta entrega no reconstruye snapshots
históricos de archivos que no los tenían.

## Verificación y continuidad

Comandos:

```bash
cd backend
BP_PYTHON=python bash tools/sales_ai/offline.sh group-e
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-e-replay.json
```

El informe `group-e-report.json` registra los resultados y límites de la ejecución. Hay pruebas
por el coordinador, estado y despachador reales, con modelo/proveedores simulados: T01, T02,
T06–T10 en lo correspondiente a E; seis proyectos exportados por SMS/WhatsApp; contrato malformado,
hechos/acciones/URLs inventados, reparación y fallback; Meta; material directo/alternativo;
archivos cifrados, faltantes, sustituidos y corruptos; referencias y exclusiones; multipartes;
reintento; cambios de aprobación y control humano durante la composición.

No se añaden migraciones SQL. La base acumulada requiere las migraciones de C, incluida
`20261108_sales_visit_context`, antes de arrancar API/worker. Se conservan los interruptores de
activación de B, apagados por defecto y con allowlist explícita de Project. El simulador anterior
no representa esta ruta. No se cambia frontend, el modelo del producto ni los prompts publicados.

No se desplegó ni se enviaron mensajes/Calendar reales. No se ejecutó el modelo real, la aceptación
completa T01–T26 ni la prueba real de los archivos comerciales exportados. Docker no está instalado:
la disposición de Actions se comprueba con copias físicas aisladas; no equivale a construir la imagen
ni ejecutar el workflow remoto. El ciclo posterior de citas y su continuidad se conserva para F.
