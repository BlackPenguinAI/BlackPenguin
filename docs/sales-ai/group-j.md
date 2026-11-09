# Grupo J — Moderación gradual y contexto operativo (pasos 16 y 17)

Base: `ffe90014abc18f2aa45633ce01fc6f78099c129a`, main con A–I. La implementación está preparada;
la aceptación visual en navegador de escritorio/móvil sigue pendiente por las restricciones
del entorno de pruebas. No se activó la cohorte ni se modificó producción.

## Moderación

El contrato interno admite una clasificación opcional con evidencia literal del mensaje.
Desacuerdo y lenguaje soez aislado no generan sanciones. Una solicitud ajena al ámbito recibe
una orientación breve. El abuso personal directo recibe una advertencia; sólo otro mensaje
posterior a una advertencia aceptada por el proveedor, dentro de 24 horas, puede ocasionar
una pausa por `REPEATED_ABUSE`. Un webhook repetido conserva el incidente original. Una
advertencia rechazada o incompleta no cuenta como recibida. Aceptación por proveedor no
equivale a entrega al teléfono ni a lectura.

Las amenazas propias concretas y los intentos de extracción de información privada o
credenciales reciben controles inmediatos con motivos `THREAT` o `SECURITY`. Se conservan
los controles de permisos de cada acción. El aviso y las pausas desplazan las solicitudes
comerciales del mismo turno, evitando efectos secundarios durante esa respuesta.

El incidente conserva ámbito, mensaje, evidencia, decisión, advertencia previa, recibo y caso
humano. Se excluyen citas/reportes y negaciones en los patrones de abuso; la inferencia del
modelo requiere evidencia actual y umbral conservador para clasificaciones graves. Esto es
una política acotada, no una garantía de detectar todas las formas de abuso. La evaluación
con el modelo real corresponde a K.

Resolver un falso positivo en la cohorte nueva descarta sólo el incidente revisado y su
advertencia antecedente. No añade una lista permanente de textos permitidos. Un mensaje
futuro se evalúa de nuevo; revisar el caso nunca restablece consentimiento retirado. Se exige
consentimiento vigente para reanudar. El comportamiento legado fuera de la cohorte conserva
su mecanismo de revisión; la reanudación tampoco permite opt-out o consentimiento ausente.

## Agent, Schedule y Monitor

Las tres pantallas reutilizan un panel de contexto. Distingue la propiedad consultada de las
visitas registradas, y muestra propuestas con vencimiento, esperas, tareas, intervenciones,
moderación, estado del motor, trabajo entrante, sincronizaciones y recibos. Las fechas de las
citas se etiquetan explícitamente en UTC. Los intervalos de espera conservan su zona guardada.
El panel se adapta mediante reglas de pantalla y contenedor; no se afirma validación visual
de esas reglas hasta ejecutar los recorridos de navegador pendientes.

Agent y Schedule actualizan el contexto cada diez segundos; Monitor usa su consulta auditada
existente. Cambiar la selección cancela peticiones anteriores y evita pintar otra oportunidad.
Los fallos de carga son visibles y permiten actualizar. Monitor y Schedule son de lectura en
este panel. Los administradores/assistants pueden solicitar desde Agent un reintento de
sincronización con explicación; el backend vuelve a comprobar ámbito, rol y reserva vigente,
registra auditoría y encola la comprobación. La cola no significa sincronización completada.
La operación de reemplazo conserva la propiedad de sus efectos y la cancelación reutiliza
su mecanismo de recuperación. No se ofrece reenvío ciego de avisos de disponibilidad inciertos.

Los endpoints `/sales-agent/conversations/{id}/operational-context` y
`/sales-agent/meetings/{id}/operational-context` aplican permisos de Company, Project y Sales.
Un Sales anterior sólo accede al contexto acotado de una cita que aún tiene asignada. Una
selección histórica en Monitor no se completa con datos de la oportunidad actual del hilo.
Las respuestas no se almacenan en caché. La consulta actual y las citas siguen siendo fuentes
separadas: consultar otra propiedad no cambia la reserva.

La traza cliente expone referencias de configuración, modelo, resultados y validaciones
permitidas. Oculta prompts completos, respuestas crudas, claves y razonamiento privado. El
export administrativo conserva la configuración histórica aplicada y JSON estructurado
validado, con redacción recursiva; las respuestas crudas que no son JSON se ocultan. Los
enlaces a materiales aprobados del chat autenticado permanecen utilizables en su ámbito.

## Aplicación y reversión

Aplicar los diferenciales sobre main con A–I. Ejecutar `alembic upgrade head` con la
configuración del entorno antes de iniciar API/worker. Nueva revisión aditiva:
`20261108_sales_moderation`, posterior a `20261108_sales_wait_requests`.
Compilar y publicar el frontend con el procedimiento del proyecto; no se hizo despliegue.
No cambian el modelo publicado ni los prompts publicados. El prompt interno pasa a
`sales-understanding-prompt/2.7`; el campo de moderación es opcional. Las banderas del flujo
nuevo siguen desactivadas por defecto y requieren la lista explícita de Projects.

Para revertir, detener primero el procesamiento nuevo según el procedimiento del entorno,
restaurar API/worker/frontend compatibles y conservar la tabla de incidentes, revisiones,
citas, esperas y recibos. No borrar evidencia ni ejecutar un downgrade destructivo como
parte de la reversión operativa.

## Verificación reproducible

- Backend: `BP_PYTHON=python bash tools/sales_ai/offline.sh group-j`, `baseline` y
  `replay /tmp/group-j-replay.json` desde backend. Proveedores e interpretación simulados.
- Frontend desde frontend: `TZ=UTC npx ng test --watch=false --ts-config=tsconfig.sales-ai-j.spec.json --include='src/app/pages/client/agent/agent.spec.ts' --include='src/app/pages/client/sales/sales.spec.ts' --include='src/app/pages/monitor/monitor*.spec.ts' --include='src/app/shared/ui/agent-context/agent-context.spec.ts'`.
- Build: `npm run build` desde frontend.
- Renderizado del formulario de revisión y del panel: `TZ=UTC npx vitest run src/app/pages/client/agent/agent-review-render.spec.ts src/app/shared/ui/agent-context/agent-context-render.spec.ts --environment jsdom` desde frontend (nueve pruebas adicionales a las 57 anteriores; 66 en total).
- Navegador pendiente: ejecutar `node tools/sales-ai/group-j-preview.cjs` desde frontend para
  servir el build como SPA en localhost:4180 y, en otra terminal, ejecutar
  `node tools/sales-ai/group-j-browser.cjs` con Playwright 1.62.1 instalado y su Chromium
  descargado mediante `npx playwright install chromium`. `BP_CHROME` permite elegir otro
  ejecutable ya instalado, sin cambiar la configuración de la aplicación.
  El script usa datos sintéticos, simula las API y bloquea tráfico externo. Prepara seis
  recorridos: Agent/Schedule/Monitor a 1440 y 390 px, con reanudación, respuesta manual y
  reintento. El script no fue validado ejecutándolo en este entorno: Chromium no arrancó
  (`socket(): Operation not permitted`) y el navegador alternativo no alcanzó localhost.
  Resolver cualquier fallo del recorrido antes de declarar aceptada la interfaz.

La continuación incorpora ocho pruebas nuevas de renderizado: consulta y reserva separadas,
banderas runtime/flujo independientes, espera incierta, reintento con explicación, rechazo por
permisos, lectura acotada, evidencia escapada y recuperación tras error. No sustituyen un motor
de layout real ni prueban el ancho de una pantalla. Se comprobó también el servidor de preview:
rutas SPA, JavaScript compilado, rechazo de API sin mocks y archivos inexistentes.

Se añade `.github/workflows/sales-ai-group-j-ui.yml`, exclusivamente `workflow_dispatch`,
con permisos de repositorio de lectura y sin secretos ni pasos de despliegue. Prepara las
66 pruebas, el build y los seis recorridos de navegador. Debe ejecutarse manualmente desde
Actions sobre la revisión que contenga estos cambios; este trabajo no lo ejecutó ni lo aprobó.
No modifica el workflow de producción existente. El recorrido usa el Chromium de Playwright,
reconoce correctamente las rutas con barra final y selecciona las citas por su bloque visual.

Los resultados exactos y las limitaciones están en `group-j-report.json`. No se ejecutaron
llamadas al modelo real, Calendar, SMS o WhatsApp, ni contención real en PostgreSQL. El
build mantiene dos advertencias existentes de presupuesto SCSS en Agent y Schedule.
K (18–19) continúa la evaluación e integración; L (20–21), la aceptación real y entrega.
