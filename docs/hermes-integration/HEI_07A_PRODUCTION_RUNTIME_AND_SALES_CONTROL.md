# HEI-07A — Production Runtime & Sales Agent Control

Base: `503b38bd2f319b9c7560ba6aa2d199050098d4e5`.

## Objetivo y alcance

Una sola instalación de BlackPenguin y un solo Droplet. Reutilizar los webhooks, la API, SalesInboundJob, SalesFollowUpJob, worker comercial, catálogo aprobado, PostgreSQL, despacho, recibos y Calendar existentes. Incorporar únicamente el contenedor privado `bp-hermes`, con SDK fijado por el Dockerfile existente. `bp_worker_prod` sigue siendo el worker de onboarding. No se modifican prompts, modelos ni ejecución de Company/Project Onboarding. El selector de Sales Agent se muestra en su pestaña, y conserva los editores independientes de LangGraph y Hermes (este último en `/admin/ai-settings/hermes`).

Este release permite `closed` y `pilot`, **no `global`**. El piloto no es una certificación de producción general: Telnyx, materiales, Calendar y rollback deben probarse realmente en HEI-07B/C. El despliegue no selecciona Hermes automáticamente. No se crean tablas, bases nuevas, dominios ni webhooks públicos adicionales. No se usan overlays o monkeypatches en producción.

## Paso 1. Subir y desplegar cerrado

1. Descomprimir el ZIP conservando todas las rutas, incluida `.github/workflows/deploy.yml`, y subir mediante GitHub Upload files. Los archivos son completos, no parches. No agregar otro YAML.
2. Commit sugerido: `feat(hermes): integrate scoped production pilot and sales-only engine control`.
3. Verificar en Settings > Secrets and variables > Actions > Variables que `HERMES_RELEASE_MODE` no exista o sea `closed`. No configurar todavía el piloto.
4. Revisar el workflow habitual `Deploy Black Penguin API, Worker & Frontend to DigitalOcean`: regresión completa, Sales acceptance, frontend y nuevo job `Build private Hermes production candidate`. Este job construye la imagen incluso en modo cerrado, ejecuta smoke del SDK y pruebas del contrato piloto. En modo cerrado no se transfiere/arranca el contenedor nuevo. Revisar también la evaluación aislada si se ejecuta.
5. Entrar a `/admin/ai-settings`: Company Onboarding y Project Onboarding deben conservar sus editores sin selector; Sales Agent debe mostrar el selector y enlaces de configuración. LangGraph debe seguir seleccionado. Hermes debe estar bloqueado. Comprobar la operación ordinaria.

Las pruebas históricas de staging con verificación de hashes fijados siguen siendo evidencia del commit anterior, no una certificación de este candidato. No cambiar esas referencias ni reejecutar ciegamente el workflow HEI-06A.2 sobre este nuevo backend: su control de integridad puede rechazar las modificaciones productivas deliberadas.

## Paso 2. Preparar el piloto real (solo tras el paso 1)

Usar la interfaz actual para crear/identificar un lead de prueba autorizado, no un lead de cliente real, con `is_test=true`, no demo, proyecto no demo y aprobado, consentimiento concedido, agente activo, conversación Telnyx SMS o WhatsApp existente, número de prueba controlado y ruta de proveedor vigente. Un lead demo o una conversación de simulación no son aptos. El operador debe controlar el número destinatario y los recursos de Calendar de prueba. Si la interfaz no permite crear esa oportunidad con sus atributos correctos, detenerse y diagnosticar; no modificar directamente los registros para saltar validaciones.

Si se conocen los IDs del lead, pueden consultarse los IDs exactos de sus conversaciones con una operación de solo lectura desde el Droplet. No compartir la salida con datos personales de clientes. Ejemplo (introducir solamente el ID de un lead propio de prueba):

```bash
read -r -p 'ID del lead de prueba: ' PILOT_LEAD_ID
docker exec -i -e PILOT_LEAD_ID="$PILOT_LEAD_ID" bp_api_prod python - <<'PY'
import os,json
import app.db.base
from app.db.postgres import SessionLocal
from app.modules.sales_crm.models import Lead
from app.modules.sales_agent.models import SalesConversation
with SessionLocal() as db:
    lead=db.get(Lead,os.environ['PILOT_LEAD_ID'])
    assert lead and lead.is_test and not lead.is_demo and not lead.deleted_at
    rows=db.query(SalesConversation).filter_by(lead_id=lead.id,provider='telnyx').all()
    print(json.dumps([dict(company_id=c.company_id,project_id=c.project_id,lead_id=c.lead_id,conversation_id=c.id,channel=c.channel,paused=c.is_paused) for c in rows],indent=2))
PY
```

En GitHub > Settings > Secrets and variables > Actions:

| Tipo | Nombre | Valor |
|---|---|---|
| Variable | `HERMES_RELEASE_MODE` | `pilot` |
| Variable | `HERMES_PILOT_UNTIL` | UTC ISO exacto `YYYY-MM-DDTHH:MM:SSZ`, futuro y máximo 7 días desde el despliegue |
| Secret | `HERMES_INTERNAL_TOKEN` | 64 caracteres hex minúsculos, generar con `openssl rand -hex 32` |
| Secret | `HERMES_PILOT_SCOPES` | JSON en una sola línea, 1–5 oportunidades exactas |
| Secret opcional | `HERMES_PILOT_OPENROUTER_API_KEY` | Clave de inferencia; si no existe se reutiliza `OPENROUTER_API_KEY` del deploy existente |

Ejemplo de estructura (sustituir todos los placeholders, no usar IDs ni teléfonos de clientes):

```json
[{"company_id":"<UUID-company>","project_id":"<UUID-project>","lead_id":"<UUID-lead>","conversation_id":"<UUID-conversation>","test_phone":"<numero-E164-controlado>"}]
```

Cada canal requiere su conversación exacta; no usar comodines. El token, las claves y el JSON real son secretos de GitHub, nunca archivos del repositorio ni mensajes de chat. Confirmar la fecha en UTC. Configurar el modo `pilot` al final, cuando estén completos los demás valores. Antes de cualquier despliegue o cambio de alcance, seleccionar LangGraph y dejar que los efectos pendientes de Hermes se reconcilien. No cambiar variables mientras un deploy está en curso.

Ejecutar manualmente **el workflow habitual de deploy** sobre main. El candidato se construye en CI, se transfiere con checksum y revisión, se inicia antes de detener los servicios actuales, y valida los registros del piloto mediante lectura. El SDK usa red bridge privada con nombre `bp-hermes-private`, sin puerto publicado, 1 vCPU / 1536 MiB de RAM, UID del Dockerfile y sin credenciales directas de Telnyx o Calendar. El API se conecta a esa red y conserva sus puertos actuales. El SDK utiliza la misma base de datos productiva para los contratos existentes de preparación, con la misma conexión del backend; no es una base aislada ni una identidad DB de privilegio mínimo. La red no implementa allowlist de egress. El SDK tiene acceso a OpenRouter y la base de datos, no un sandbox de datos a nivel SQL. Por eso no ampliar la autorización sin revisar el aislamiento y las pruebas reales.

Preflight: al menos 2 vCPU del host, 2 GiB de RAM **disponible** y 6 GiB libres en almacenamiento Docker (umbrales conservadores, no medición de carga). Si no se cumplen, se cancela el despliegue piloto; no contratar otro Droplet ni reducir límites a ciegas. El workflow existente puede realizar un breve reinicio de API/frontend/worker. No se promete zero downtime.

## Paso 3. Selección administrativa

Con el despliegue piloto exitoso, abrir `https://blackpenguin.ai/admin/ai-settings`, pestaña Sales Agent. Abrir Hermes settings y publicar una política válida y habilitada de Hermes; preservar la política comercial ya certificada y usar un modelo permitido. Volver a Sales Agent y actualizar el estado. `Private SDK ready for pilot` significa identidad de imagen/revisión/alcance, import del SDK y conexión DB verificados; no significa aceptación de OpenRouter ni Telnyx. Elegir `Select Hermes`, escribir la nota de cambio, confirmar y aplicar. La selección es auditada en los registros existentes. El UI muestra `Hermes pilot / LangGraph`: solo las oportunidades autorizadas usan Hermes para eventos elegibles. Otros nuevos eventos siguen en LangGraph por política explícita, no por fallback automático. Los eventos previamente fijados conservan el motor y la política. Si un turno Hermes pierde autorización o falla, queda para revisión y no se reenvía a LangGraph automáticamente.

La selección se mantiene en la base existente. Los procesos de primer contacto determinista, las reglas de consentimiento y las plantillas de WhatsApp siguen a cargo de BlackPenguin. El piloto no convierte automáticamente toda la automatización comercial en inferencia del SDK.

## Paso 4. Prueba E2E (HEI-07B)

Primero, desde el teléfono de prueba autorizado, enviar una consulta libre sobre una propiedad real aprobada (inglés). Verificar el mensaje recibido en Telnyx, SalesInboundJob, AgentRun Hermes, respuesta recibida en el teléfono, recibo y Conversation Inspector. Realizar la segunda consulta sin repetir el nombre de la propiedad, revisar estado. Después probar WhatsApp, medios aprobados, preferencias, opciones, citas, Calendar, reprogramación/cancelación, seguimientos, opt-out y takeover. Usar solamente recursos y calendarios de prueba autorizados y revertir las citas de prueba por las vías normales. Comprobar que otro lead no autorizado permanece en LangGraph y que onboarding no cambia. No ejecutar pruebas indiscriminadas con clientes reales.

## Rollback y cierre

Seleccionar LangGraph desde el mismo panel antes de que expire el piloto o de volver a desplegar. No editar `active_sales_engine` directamente en PostgreSQL. Verificar recibos de efectos ya iniciados, dejar pendientes inciertos en revisión; no repetir eventos. Las nuevas interacciones vuelven a LangGraph. No hay fallback silencioso. El cambio de selector no garantiza cancelar una petición ya iniciada. Si se pierde el SDK, la UI permite volver a LangGraph. Para retirar el SDK, después de seleccionar LangGraph, cambiar `HERMES_RELEASE_MODE=closed` y ejecutar el deploy habitual. No borrar volúmenes ni base de datos. La restauración de imágenes y configuración está integrada en el trap del deploy, pero su ejecución en el Droplet debe verificarse.

## Validación realizada y pendiente

20 pruebas unitarias locales sobre el código recuperado, con dobles de DB y HTTP, y comprobaciones estáticas Python/YAML/Bash. No hay ejecución local de Docker, backend completo, Angular, inferencia ni proveedores. La aceptación del despliegue real y rollback queda pendiente; no autorizar alcance global con este release. HEI-07B valida servicios reales y HEI-07C incorpora activación global con evidencia y rollback.
