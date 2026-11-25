# BP-HERMES-P04 — Entrega 3: herramientas y operaciones (Upload Ready)

**Repositorio destino:** https://github.com/BlackPenguinAI/BlackPenguin

**Commit base:** `ba65b830acb1fd721465c65afd8985de7309b6bb` (Entrega P01 + P23 incorporadas)

**Referencia Hermes v13.3.3:** `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`

El ZIP es **diferencial**: únicamente contiene archivos NUEVOS o MODIFICADOS, completos y con rutas relativas al repositorio. **No necesitas ejecutar `apply.sh`, parches, comandos de Git o scripts antes de subir los archivos.**

## Uso con GitHub Upload files

1. Descomprime el ZIP en tu computadora.
2. En GitHub crea preferiblemente una rama `feature/hermes-sales-p04` desde el commit base.
3. Sube **todos** los archivos extraídos por `Upload files` conservando las rutas `backend/...` y `docs/...`.
4. Revisa el PR, el build y la batería de pruebas antes de integrar cambios en `main`.

**Precaución:** el workflow `.github/workflows/deploy.yml` de BlackPenguin despliega automáticamente un push a `main`. Como hay un nuevo modelo en `backend/app/db/base.py` y una migración Alembic, el workflow también intentará `alembic upgrade head`. La migración crea la tabla vacía `hermes_sales_operations`; no borra datos ni cambia rutas productivas. Aun así, usa una rama y/o staging antes de hacer merge.

## Qué agrega

- `BPOperationalDraftPort`: disponibilidad real de BP como *lectura*, opciones de día/hora, selección contextual, propuestas de reserva/cancelación/reprogramación, materiales autorizados y solicitudes de contacto humano.
- Persistencia de propuestas solo cuando la respuesta exacta quedó registrada como mensaje outbound de simulación.
- `execute_p04_simulation_operation`: transacciones de **simulación controlada** con permisos por empresa/proyecto/lead, verificación de intención y consentimiento, bloqueos, revisiones CAS y recibos idempotentes.
- Reutilización de la agenda, `SalesBookingOperation`, `SalesCancellationOperation`, `SalesRescheduleOperation`, materiales y `HumanInterventionCase` existentes de BP, sin invocar la orquestación LangGraph.
- Nueva tabla/ORM `HermesSalesOperation`, migración Alembic aditiva y pruebas.

## Pruebas ejecutadas

**155 pruebas locales aprobadas**, compilación Python exitosa. Comando reproducible en `docs/hermes-integration/P04_DEPLOYMENT.md`. Pruebas con SDK Hermes simulado y base SQLite aislada; no se realizó una ejecución end-to-end en PostgreSQL ni contra OpenRouter/Google Calendar.

## Lo que NO habilita

- NO conmuta el agente productivo desde LangGraph hacia Hermes.
- NO se conecta a `live_service`, `live_worker` ni webhooks entrantes.
- NO envía SMS/WhatsApp ni sincroniza Google Calendar.
- NO crea citas para leads reales; el executor exige `simulation` + `is_demo`.
- NO modifica el perfil CRM persistentemente desde Hermes: esta escritura queda bloqueada.
- NO administra todavía Hermes desde Staff Admin ni modifica Angular.

**Siguiente fase:** P5+P6 configuración global desde Staff Superadmin + UI Angular 21. P7 requiere pruebas E2E de runtime Hermes real y PostgreSQL, más pruebas de concurrencia/efectos reales en staging. P8 realiza la sustitución definitiva del motor.

## Commit recomendado (inglés)

`feat(hermes): add scoped operational tools and simulation effect receipts`

Descripción:

```
- Add scoped Hermes scheduling, booking, cancellation, rescheduling, and asset draft tools.
- Reuse BlackPenguin business services behind transactional simulation-only execution.
- Persist idempotent operation receipts and enforce delivered-offer consent checks.
- Add an additive Alembic migration and P04 regression tests.
- Keep production messaging and the legacy sales engine unchanged until cutover.
```
