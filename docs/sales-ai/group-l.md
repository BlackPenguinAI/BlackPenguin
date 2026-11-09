# Grupo L — Aceptación y entrega verificable (pasos 20 y 21)

Base: `41c4abee4e47e02d2c77d57ca8a6961844a6ebb8`, main actualizado con K.
Estado: **entrega preparada; aceptación real y despliegue pendientes**. K conserva pendientes
modelo real, contención PostgreSQL, revisión comercial y navegador. No hay credenciales de
servicios/DB ni entorno y contacto de prueba expresamente identificados en esta ejecución.
No se contactó a ningún lead ni se eligió un teléfono del CRM por inferencia.

## Entregables

- `group-l-live-acceptance.md`: recorrido SMS/WhatsApp y evidencia que debe recogerse.
- `group-l-deployment-rollback.md`: aplicación, comprobación de versiones y reversión sin perder estado.
- `group-l-acceptance-template.json`: registro vacío; no equivale a autorización de envío.
- `group-l-migration-inventory.json`: cadena y hashes de migraciones existentes. No hay migración L.
- `release_audit.py`: lectura acotada de configuración/versiones, colas, recibos y propuestas.
- `release_checklist.py`: validación local de referencias de evidencia; nunca envía ni despliega.
- `frontend/tools/release-stamp.cjs`: identidad pública del build en `/release.json`.

## Auditoría de versión y estado

Ejecutar **por separado** dentro de los entornos de API y worker, con las credenciales de
lectura que el operador autorice para ese entorno. Sustituir las variables por UUID del ámbito
de prueba autorizado. No cargar una `.env` de producción para una prueba offline.

```bash
python -m tools.sales_ai.release_audit --service api \
  --company-id "$BP_TEST_COMPANY_ID" --project-id "$BP_TEST_PROJECT_ID" \
  --output /tmp/release-api.json
```

Repetir con `--service worker` en el worker. El parámetro etiqueta el origen declarado; el
operador debe conservar la evidencia de en qué contenedor se ejecutó. El commit procede de
`APP_COMMIT_SHA`; comparar también el digest/label de la imagen y la salud/progreso del worker.
Una CLI ejecutada en el worker no demuestra por sí sola que su bucle esté procesando trabajos.

La auditoría usa transacción read-only en PostgreSQL y `query_only` temporal en SQLite. No llama
a proveedores ni inicializa o repara tablas. Respeta Company/Project, no exporta claves, prompts,
teléfonos ni JSON de propuestas; conserva referencias y hashes. Selecciona la versión publicada
de Sales con la misma prioridad de tenant/global que el runtime y señala diferencias con el draft.
Los conteos usan los Project IDs guardados en cada tabla; auditar todos los Projects origen/destino
cuando haya operaciones cruzadas. Para más de 100 estados, continuar con `--after-state-id` usando
`next_state_id` hasta obtener `null`; detener la actividad antes de interpretar ese inventario como
un corte estable para rollback. El resultado dice `INSPECTED_NOT_ACCEPTED`, no aprobación de L.

Frontend: después de compilar, `APP_COMMIT_SHA=<SHA_COMPLETO> npm run stamp:release` genera
`dist/frontend/browser/release.json`. Contiene commit y hash de los assets públicos, sin secretos.
Un build local sin SHA queda `unknown` y `commit_known=false`. El Dockerfile utiliza `npm ci`,
el argumento `APP_COMMIT_SHA` existente y el stamp después de compilar. Nginx sirve el JSON sin
caché y devuelve 404 si falta. No se construyó ni desplegó una imagen Docker en este entorno.

El workflow manual `sales-ai-group-l-release.yml` prepara la construcción de esa imagen y la
comprobación del label, `nginx -t` y el stamp dentro de la imagen. No publica imágenes ni despliega;
no usa secretos de producción y los contenedores de comprobación se ejecutan sin red. Su ejecución
en GitHub sigue pendiente. `BP_BUILD_CONFIGURATION` conserva `production` por defecto y permite
usar `production,offline-ci` en el laboratorio sin descarga de fuentes.

El endpoint API existente `/api/v1/health/version`, el stamp frontend, los labels de imagen y
los informes API/worker permiten contrastar una revisión concreta. Comprobar además readiness,
head de Alembic, versión/hash de configuración y una ejecución real completa. Coincidir en el SHA
o tener un healthcheck verde no demuestra entrega al teléfono, agenda correcta o aceptación.

## Registro de aceptación

Copiar el template a una ubicación privada fuera del repositorio público y completar sólo con
hechos comprobados. La referencia de contacto debe apuntar a un registro privado que identifique
el número exacto, propietario, consentimiento, entorno, Company/Project, canales y ventana autorizada.
El JSON público de resultado no repite esos datos. No pegar tokens ni claves en argumentos o logs.

```bash
python -m tools.sales_ai.release_checklist --input /ruta/privada/aceptacion.json \
  --evidence-root /ruta/privada/evidencias --output /tmp/checklist-result.json
```

El validador exige revisión, tiempos, SHA del candidato, tres componentes coincidentes y archivos
de evidencia con hashes correctos; rechaza rutas fuera del directorio permitido. No interpreta el
contenido de una captura/recibo ni verifica firmas externas: hashes sólo prueban los bytes locales
referenciados. Incluso un documento completo devuelve `DOCUMENTS_COMPLETE_OPERATOR_REVIEW_REQUIRED`,
`deployment_authorized=false` e `independent_provider_verification=false`. El operador debe comprobar
independientemente la autorización y los efectos reales antes de aprobar pruebas o publicación.
El template sin completar devuelve `BLOCKED`; no se sustituyen los pendientes de K por checkboxes.

## Configuración por revisar antes de publicar

Conservar `openai/gpt-4o-mini` y la guía comercial publicada, salvo un cambio posterior explícitamente
revisado. Revisar el draft frente al hash/versión actualmente publicados; no importar el fixture de
evaluación como si fuera configuración vigente. Para una cohorte de prueba, preparar una propuesta
con `mode=active`, `scope=cohort` e IDs exactos de Company, Project y lead de prueba; revisar que no
incluya un ámbito global o comodines. La propuesta se fusiona sobre el pack vigente conservando
las personalizaciones, nunca reemplazando todo el objeto por un JSON mínimo.

Los interruptores de plataforma, allowlist de Projects, canal/proveedor, consentimiento, capacidades
de onboarding y conexiones Calendar también requieren revisión. No se publicó ese cambio ni se
activó la cohorte. El operador debe vincular la aprobación a la versión exacta que realmente despliegue.

## Verificaciones locales

Desde backend: `BP_PYTHON=python bash tools/sales_ai/offline.sh group-l` y `baseline`.
Desde frontend: `TZ=UTC npm run test:sales-ai-k`, `npm run test:release` y
`npm run build -- --configuration=production,offline-ci` (evita sólo incrustar fuentes externas).
Consultar `group-l-report.json` para resultados y límites. Las pruebas son sintéticas/aisladas.
Los reportes `BLOCKED` documentan la ausencia de accesos; no son pruebas reales aprobadas.

**Aplicar:** revisar el parche sobre main con K. El ZIP contiene sólo archivos nuevos/modificados,
instrucciones, inventario de migraciones y evidencia. No se hizo push, merge, despliegue, migración,
publicación de prompts ni envío real. No confundir la entrega de estos archivos con el cierre de L.
