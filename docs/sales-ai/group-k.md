# Grupo K — Evaluación e integración (pasos 18 y 19)

Base: `306dd648b0e8749973e4ce5a78a1ee2cccd82576`, main con J refinado.
El grupo queda parcialmente ejecutado: las comprobaciones locales se registran en
`group-k-report.json`. El modelo real, PostgreSQL paralelo y la aceptación visual requieren
recursos que no están disponibles en este entorno. No se da autorización para pruebas por
canales reales ni se considera cerrado K por haber preparado sus herramientas.

## Evaluación con el modelo del producto

Se conserva `openai/gpt-4o-mini`. La copia `published_sales_v8_20261108.json` procede de la
versión global publicada 8 del diagnóstico del 8 de noviembre. Excluye claves, campos de
runtime y otros servicios. Es una copia histórica para evaluar; no afirma ser la configuración
actual de producción. El runner publica esa copia sólo en una SQLite efímera, con versión
local 1 e identificación por hash. Los catálogos reales exportados y sintéticos permanecen
identificados por origen. No se sobrescriben sus archivos fuente.

Desde backend, preparar el conjunto sin inferencia:

```bash
BP_PYTHON=python bash tools/sales_ai/evaluate.sh --mode prepare \
  --agent-pack tests/fixtures/sales_ai/published_sales_v8_20261108.json \
  --catalog tests/fixtures/sales_ai/real_catalog_20261108.json \
  --repeats 3 --max-calls 80 --budget-usd 3 --output /tmp/model-plan.json
```

En un entorno aislado con `OPENROUTER_API_KEY` configurada de forma segura, cambiar a
`--mode real` y usar otro archivo de salida. No poner claves en argumentos ni en el repositorio.
La ejecución local de ese comando quedó `BLOCKED / OPENROUTER_API_KEY_MISSING`, sin llamadas
ni gasto. No se usó una clave ficticia para simular que se evaluó el modelo real.

El conjunto representativo prepara 24 recorridos en el catálogo real: catálogo/saludo,
solicitud mixta, referencia ordinal y moderación, por SMS/WA y tres repeticiones independientes.
Se puede usar el catálogo sintético por separado. `--all-projects` amplía el conjunto a todos
los Projects; no elimina límites ni convierte un resultado parcial en aceptado. No cubre por
sí solo T01–T26 ni evalúa con modelo real toda la agenda. Los IDs seleccionados quedan en el JSON.

El padre ejecuta el coordinador, intérprete, compositor, estado y dispatcher de producción,
con mensajería y Calendar simulados y red bloqueada en el harness. Sólo un proceso hijo hace
la inferencia al endpoint fijo de OpenRouter. Los JSON Schema son los del código; las respuestas
no se juzgan por igualdad literal de redacción. Se comprueban estado, referencias, conservación
de necesidades, ausencia de operaciones no autorizadas, moderación y deduplicación.

El hijo usa máximo 2048 tokens, entrada de hasta 64 KB, timeout, sin redirecciones ni cambio
de modelo y sin reintentos HTTP automáticos. Cuenta cada llamada/reparación de producción y
reserva presupuesto antes de iniciarla. Configura `provider.max_price` a USD 1/2 por millón
de tokens de entrada/salida y USD 0 por petición; es un techo de selección, no una declaración
de la tarifa actual del modelo. Documentación primaria consultada:
https://openrouter.ai/docs/guides/routing/provider-selection#max-price

La reserva conservadora basada en bytes se conserva ante timeout/cancelación: se desconoce
si el proveedor cobró. Se registran latencia, uso/coste reportado y coste desconocido por separado.
No se promete un límite contable absoluto que incluya tasas de cuenta u otras reglas del proveedor;
usar además una clave de pruebas con límite de gasto en el proveedor. La suma observada no reemplaza
la reserva cuando falta `usage.cost`. Un presupuesto agotado produce resultado incompleto, no éxito.

Los reportes no guardan claves ni razonamiento privado. Incluyen mensajes sintéticos de prueba y
respuestas comerciales redactadas, hashes de configuración/peticiones, resultados semánticos y
variación entre repeticiones. La revisión de calidad comercial queda `PENDING`: un resultado verde
no se convierte automáticamente en aprobación por un juez LLM.

Separar el diagnóstico antes de proponer otro modelo:

| Señal | Revisar primero |
|---|---|
| Falta de clave, HTTP 401/429, red o timeout | Acceso/proveedor/límite de ejecución |
| Contexto demasiado grande o datos vencidos | Construcción del contexto/exportación |
| Versión/hash incorrectos o guía ambigua | Configuración y publicación |
| JSON/evidencia inválidos persistentes | Contrato/interpretación; luego capacidad del modelo |
| Estado, permisos o efectos incorrectos con contrato válido | Arquitectura/backend |
| Tono poco útil con hechos correctos | Revisión comercial y playbook; comparar modelos sólo con evidencia |

## Regresión y corrección

Las pruebas K conectan espera → aviso → reserva → consulta de otra propiedad → reemplazo →
cancelación → nueva consulta, en ambos canales. También reabren la sesión SQL después de un
despacho fallido y verifican que el reemplazo persistido no se repite ni vuelve a inferir.
Los callbacks firmados se ejecutan mediante ASGI en memoria, sin servidor del proveedor.
Se verifican firma manipulada, duplicados y eventos tardíos: `read`/`delivered` no retroceden
a `sent`, `queued` o `failed`. Se corrige esa regresión en `provider_router._apply_status`.
Las operaciones de salida y sus mensajes usan el mismo orden de bloqueo al procesar el recibo.
La contención real de esos bloqueos no se afirma a partir de SQLite.
La corrección del helper compartido afecta a recibos de Twilio/Telnyx, incluida la ruta legado;
no depende de activar el nuevo flujo. No se cambian las banderas ni los permisos del canal.

```bash
BP_PYTHON=python bash tools/sales_ai/offline.sh group-k
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/replay.json
```

El wrapper sigue siendo offline para modelo/mensajería. PostgreSQL se habilita sólo pasando
`BP_POSTGRES_TEST_URL` con una base desechable cuyo nombre termine en `_test`. El wrapper rechaza
otro nombre antes de comenzar; los tests comprueban además `current_database()` y aíslan sus
esquemas. No utiliza `DATABASE_URL` de producción. Los cuatro casos heredados quedan omitidos
sin esa URL. No hay PostgreSQL ni Docker instalados localmente.

La regresión frontend completa tiene un arranque de pruebas explícito (Router/Translate/HTTP
en memoria), medios/observadores simulados y limpieza de globales entre casos. Corrige imports
obsoletos de tests generados y expectativas de creación de drafts; no cambia la UI de producto.
Los dos archivos DOM directos se ejecutan por Vitest con su propio entorno (9 pruebas). Desde frontend ejecutar `TZ=UTC npm run test:sales-ai-k` (430 pruebas CLI y 9 DOM). Ver los comandos
exactos y resultados finales en el reporte y en el workflow.

La compilación normal pasó durante la primera verificación; un intento posterior falló al
descargar CSS de Google Fonts (HTTP 403). Para CI sin esa dependencia se añade una configuración
combinable que mantiene la optimización de scripts/estilos y omite sólo incrustar fuentes externas:
`npm run build -- --configuration=production,offline-ci`. Mantiene los enlaces de fuentes del
HTML y no altera el modo de compilación predeterminado. El reporte distingue ambos resultados.

`.github/workflows/sales-ai-group-k-regression.yml` es manual, sin secretos ni despliegue.
Incluye PostgreSQL desechable, layout físico aislado de backend, suite frontend, build y los
recorridos de escritorio/móvil de J. Se entrega preparado, no ejecutado en GitHub. El workflow
de producción no cambia. Ninguna prueba visual bloqueada se registra como aprobada.

El contraste funcional de los tres recorridos está en `group-k-graph-comparison.md` y la
matriz T01–T26 en `backend/tests/fixtures/sales_ai/group_k_coverage.json`. Para cerrar K faltan
los resultados reales señalados, resolver cualquier fallo y revisar la calidad comercial.

## Aplicación

Aplicar los diferenciales sólo sobre main con J refinado. No hay migraciones nuevas en K;
el head continúa `20261108_sales_moderation`. Conservar los incidentes, reservas, esperas y
recibos existentes. Ejecutar las verificaciones antes de publicar API/worker/frontend.
No se desplegó, cambió el modelo publicado, activó la cohorte o contactó leads. La entrega
de L continúa pendiente del cierre de K y de su autorización/entorno/contacto de prueba.
