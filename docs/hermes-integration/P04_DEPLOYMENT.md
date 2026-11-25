# BP-HERMES-P04 — Upload Ready / despliegue controlado

## Base

Aplica sobre BlackPenguin `main` con P01 y P23: commit `ba65b830acb1fd721465c65afd8985de7309b6bb` (25-11-2026, UTC). El ZIP incluye archivos de código **completos** bajo rutas relativas de repositorio. No incluye `apply.sh`, `git apply` ni pasos que deban ejecutarse **antes** de subirlo.

## Subida a GitHub

1. Crear una rama, por ejemplo `feature/hermes-sales-p04`, desde el commit base.
2. Descomprimir ZIP; subir las rutas completas a GitHub **Upload files** en la rama creada.
3. Abrir un PR y verificar tests/CI. **No usar main como primera prueba**: el workflow de este repositorio despliega automáticamente al hacer push a `main` y detecta los cambios de modelos/Alembic.
4. Antes de integrar a main, preparar respaldo de DB, confirmar `alembic current`, verificar cuál es la revisión vigente y que exista P03.
5. Comprobar en un entorno de staging: `alembic upgrade head`. La migración nueva `20261125_hermes_sales_p04` crea **solo** `hermes_sales_operations` y no borra datos.
6. Validar que ninguna ruta `/api/v1/sales-agent` ni worker cambió de motor: P04 está deliberadamente **apagado** para el procesamiento real de leads.

## Pruebas locales sin proveedores

En entorno Python compatible con dependencias de backend:

```bash
PYTHONPATH=backend pytest -q \
  backend/tests/test_bp_hermes_p01.py \
  backend/tests/test_bp_hermes_p01_policies.py \
  backend/tests/test_bp_hermes_p02_catalog.py \
  backend/tests/test_bp_hermes_p03_state.py \
  backend/tests/test_bp_hermes_p04_operational_port.py \
  backend/tests/test_bp_hermes_p04_executor.py \
  backend/tests/test_bp_hermes_p04_state_validation.py
```

Los tests nuevos usan la base SQLite aislada y SDK simulado. No se requieren secretos, `OPENROUTER_API_KEY`, Telnyx ni Google Calendar para esta batería.

## Migración

- `down_revision = '20261125_hermes_sales_p03'`
- `revision = '20261125_hermes_sales_p04'`
- Tabla nueva: `hermes_sales_operations` (scope de empresa/proyecto/conversación/lead, inbox message, id de solicitud, tipo, hash, estado y resultado sin token de acceso).
- `backend/app/db/base.py` registra el nuevo ORM en la metadata Alembic.
- `downgrade()` eliminaría los recibos de operaciones de Hermes. **No ejecutar downgrade sin respaldo y autorización explícita.**

## Seguridad de release

El paquete NO toca los webhooks, `active_service.py`, `live_service.py` ni `live_worker.py`. Tampoco crea ruta nueva de administración ni activa Hermes por empresa. No se agregan variables de entorno o valores de secretos. Los componentes nuevos solo son llamados explícitamente en pruebas de simulación. Se conservará LangGraph como flujo activo hasta P8, pero no coexisten como motores de conversación para un mismo turno real.

**Todavía no anunciar que Hermes tiene reservas reales habilitadas.** Las operaciones P04 están restringidas a simulación y no envían mensajes ni sincronizan calendarios.
