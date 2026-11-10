# Evaluación automatizada del agente vigente

Base de esta entrega: `eec5714` (corrección HTTP de composición ya incorporada).
No modifica el agente de producción, sus prompts, el pipeline ni las migraciones. Añade una herramienta operativa y pruebas sin proveedores reales. Los comandos de evaluación real se ejecutan explícitamente; no se añaden llamadas pagadas a cada push de GitHub.

## Qué ejecuta

El recorrido es el existente `current_simulation.turn` → coordinador vigente → comprensión → planificación/consultas → memoria → composición → validaciones → entrega interna. No es otro chatbot con un prompt parecido. La comprensión y composición usan el modelo y configuración publicados que utiliza el agente, incluida la corrección de esquema estricto.

1. El proceso padre obtiene una instantánea consistente del proyecto mediante una transacción PostgreSQL `REPEATABLE READ, READ ONLY`. Exige Company/Project coincidentes y un perfil publicado aprobado.
2. Copia metadatos del proyecto, catálogo, unidades, materiales aprobados, reglas públicas de Company, políticas aplicables y configuración publicada. No copia leads, conversaciones, contactos, usuarios, calendarios ni credenciales de mensajería.
3. Los bytes locales de materiales aprobados se leen/decriptan y copian a almacenamiento temporal privado; no se descargan URLs externas. Se limita cada archivo y el conjunto a 100 MB. Los archivos ausentes/inaccesibles quedan registrados como limitaciones de la instantánea.
4. Un subproceso arranca en un directorio privado, sin el `.env` de producción ni sus variables de servicios, con SQLite y almacenamiento desechables. La credencial OpenRouter necesaria permanece en ese espacio temporal con permisos privados; nunca se incluye en los informes.
5. Se crean leads ficticios independientes con teléfonos ficticios distintos y conversaciones `simulation`. No se modifica el lead real de Betty. Las escrituras del motor y sus trabajos quedan en la base desechable. Se bloquean conexiones SQLAlchemy a otros motores durante la evaluación.
6. Las conexiones de red del trabajador se restringen a inferencia HTTPS de OpenRouter. Se bloquean otros destinos HTTP/DNS/TCP y envío de datagramas. No hay workers que procesen los trabajos locales. La contabilidad habitual de Company se sustituye por el contador de evaluación para evitar un segundo escritor SQLite; no se actualizan métricas reales.
7. La base temporal, la copia de materiales y la credencial se eliminan al finalizar el proceso padre. Solo permanecen los informes saneados.

## Modos

### Replay: casos reproducibles de Betty

Cuatro conversaciones independientes, 14 mensajes del lead en total:

- Presupuesto y efectivo: saludo, catálogo, USD 1.500.000, declaración de efectivo y reiteración.
- Materiales: fotos, aceptación breve y solicitud de PDF. Una aceptación solo exige compartir material si el agente realmente ofreció uno. Sin PDF aprobado o con bytes inaccesibles, la comprobación de entrega de PDF queda BLOCKED.
- Corrección y detalles: efectivo declarado, reclamación de incomprensión, financiamiento junto con otra pregunta, habitaciones y estacionamiento.
- STOP: se verifica que se guarde la baja y que no aparezcan envíos ni reservas.

Son pruebas de comportamientos del incidente, no una reproducción literal de toda la conversación original ni cobertura de todas las casuísticas de ventas.

### Adaptive: un LLM actúa como comprador

Un comprador ficticio con presupuesto USD 1.500.000 y efectivo conversa de forma dinámica, con un límite de turnos. El LLM lead recibe exclusivamente el saludo y mensajes visibles, no interpreta trazas internas ni ve el estado privado del agente. El agente no recibe el perfil privado del comprador hasta que este lo expresa. Se conservan los mensajes generados para revisarlos después.

El modo adaptativo es variable; compare versiones con el replay como base reproducible. No se garantiza determinismo del proveedor aunque los mensajes del replay sean fijos.

## Ejecutar en el servidor después de desplegar

Primera evaluación recomendada para Ashville Park 4:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.evaluation \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --project-id 854ac168-1b0b-5ef3-a68e-091b5cc82e0f \
  --mode replay --max-calls 80 --output /tmp/sales-evaluation-replay-1
```

Una evaluación adaptativa:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.evaluation \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --project-id 854ac168-1b0b-5ef3-a68e-091b5cc82e0f \
  --mode adaptive --max-turns 10 --max-calls 60 --output /tmp/sales-evaluation-adaptive-1
```

Use un directorio nuevo en cada ejecución. No se sobrescriben resultados anteriores. El proceso informa progreso por caso/turno y al final imprime un resumen breve.

Las llamadas son reales y pueden generar cargos en OpenRouter. `--max-calls` incluye comprensión, reparaciones, composición, LLM lead y LLM evaluador; no es un límite monetario exacto. La versión inicial conserva los parámetros del motor. El coste mostrado es la suma de `usage.cost` cuando lo informa el proveedor; revise `responses_with_cost`, porque el coste puede ser incompleto. El proceso padre tiene un tiempo máximo de 30 minutos. `--no-judge` permite omitir la valoración LLM, sin omitir comprobaciones de estado/seguridad.

## Recuperar resultados

Los comandos anteriores escriben dentro del contenedor. En la consola SSH del servidor:

```bash
docker cp bp_api_prod:/tmp/sales-evaluation-replay-1/report.json ./sales-evaluation-report.json
docker cp bp_api_prod:/tmp/sales-evaluation-replay-1/report.md ./sales-evaluation-report.md
```

Después, en PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-evaluation-report.json "$env:USERPROFILE\Downloads\sales-evaluation-report.json"
```

Adjunte el JSON completo para analizarlo. No lo suba al repositorio: contiene contexto comercial e información interna del agente, aunque no incluya claves ni leads reales. Copie los informes antes de reemplazar el contenedor en el siguiente despliegue.

## Qué registra y cómo decide

- Versión de código, modelo, versión/hash de configuración, revisión/hash del proyecto y contexto aprobado una sola vez.
- Mensajes del lead y las respuestas efectivamente entregadas al chat interno, no solo el borrador propuesto.
- Comprensión estructurada, intentos y fallos de validación; trazas de planificación, resultados, borradores, composición y acciones; perfil declarado después de cada turno.
- Conteo global de llamadas, tokens y coste informado por el proveedor; intentos de red bloqueados.
- Comprobaciones por código: flujo vigente, interpretación y composición, recibos internos, presupuesto/moneda, efectivo declarado, clasificación de estacionamiento, material emitido cuando aplica, preservación de la petición adicional, STOP, ausencia de outbox de proveedor y de reservas no solicitadas.
- Un LLM evaluador valora pertinencia, reconocimiento de correcciones, repetición y utilidad comercial. Debe señalar turnos existentes. Sus valoraciones se distinguen de los controles por código y no pueden convertir un fallo de estos en aprobación.

`PASS` significa que pasan las comprobaciones configuradas y las valoraciones solicitadas. `FAIL` señala problemas observados del agente o de la valoración; no que el despliegue haya fallado. `INCOMPLETE` significa limitaciones de material sin otros fallos. `ERROR` indica un problema del evaluador/configuración que impide la ejecución. La herramienta devuelve código 0 solo para PASS; 2 para otros resultados. Los informes siguen disponibles aunque la evaluación termine con FAIL.

Estos controles no constituyen una demostración universal de naturalidad, exactitud o seguridad. El juez LLM puede equivocarse; se conservan razones y turnos para contrastarlo. No se modifican prompts ni se publican cambios automáticamente según su puntuación.

## Límites

- Reutiliza el adaptador existente `simulation`, equivalente al canal SMS para renderizado y disponibilidad de materiales. No prueba entrega WhatsApp, plantillas, ventanas de conversación ni webhooks.
- No se clonan vendedores ni calendarios reales: esta entrega no evalúa disponibilidad o sincronización real de citas.
- Se usa SQLite con ejecución secuencial por caso; no sustituye las pruebas PostgreSQL de concurrencia del pipeline.
- Se crean leads nuevos sin historial personal de producción ni formularios Meta. Las conversaciones usan números distintos para evitar contaminación entre casos por historial telefónico.
- Las verificaciones monetarias del replay están centradas en el dato explícito de Betty, USD 1.500.000. El caso adaptativo usa ese mismo comprador ficticio; no cubre todos los perfiles o monedas.

## Validación de esta entrega

Pruebas offline del evaluador, esquema/composición HTTP y simulación vigente: 69 aprobadas. Incluyen un recorrido completo del motor con transporte HTTP simulado; STOP sin llamada a modelo; proceso hijo con base privada; snapshot mediante SELECT sin copiar leads; bloqueo de red; presupuesto perdido; estacionamiento mal clasificado; respuestas del juez sin evidencia; saneamiento de claves y separación de la información que ve el LLM lead.

No se han realizado llamadas reales de evaluación a OpenRouter ni una ejecución en producción durante la preparación. La primera ejecución del comando sobre el proyecto desplegado establecerá la línea base real. Los fallos de presupuesto, efectivo, materiales y estacionamiento detectados previamente no se corrigen con esta entrega: quedarán medidos para preparar la siguiente corrección.
