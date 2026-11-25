# BP-HERMES-P04 — Test report

**Fecha:** 2026-11-25. **Base:** BlackPenguin `ba65b830acb1fd721465c65afd8985de7309b6bb`.

## Resultado local

Batería focalizada que incluye P01, P02, P03 y P04: ejecutar el comando documentado en `P04_DEPLOYMENT.md`; el resultado registrado se incorpora también en `UPLOAD_READY.md`.

Cobertura incorporada de P04:

- Disponibilidad por zona horaria del proyecto, horarios de 60 minutos, fechas, franjas horarias, ausencia de slots y entrega de menús numerados.
- Selección contextual del segundo horario y bloqueo de opciones ocultas/no entregadas.
- Borrador de booking solo después de recap del inmueble/fecha/hora y confirmación explícita posterior, nunca por `OK` aislado.
- Borradores de cancelación/reprogramación con fingerprint de reserva activa y confirmación.
- Materiales solicitados explícitamente y recursos con cobertura autorizada.
- Escopos company/project/lead, permisos, prueba negativa de canal live y prueba negativa de lead no demo.
- Persistencia P04 con recibo idempotente, CAS, rollback ante fallo y replay sin duplicar acciones.
- Validación de menú contra texto realmente entregado; rechazo de recap no mostrado y oferta de otro proyecto.
- Migración aditiva Alembic P03→P04 contra SQLite in-memory; columnas contra ORM.

## Lo que estas pruebas NO demuestran

No comprueban funcionamiento real de Google Calendar OAuth, Telnyx/Twilio, Meta webhooks, OpenRouter, el SDK Hermes instalado en una imagen productiva, ni carreras PostgreSQL con varios procesos, permisos efectivos de storage o entrega efectiva de material al teléfono del lead. El executor de P04 está restringido a simulación y sus pruebas de reserva usan stubs para las operaciones dependientes de terceros.

## Criterios antes de habilitar en producción (P7/P8)

- Probar transacciones en PostgreSQL real con dos workers simultáneos, rollback y reinicio entre pasos.
- Ejecutar escenarios completos Hermes v13.3.3 con estado recuperable y catálogo de BlackPenguin: propiedad activa, preferencias primarias vs temporales, `option 2`, fecha/hora, activos y cambios de foco.
- Probar agendas compartidas y colisiones, expiración de ofertas y TZ/DST reales, cancelación/reprogramación con Calendar conectado, reintentos de sync y receipts.
- Confirmar que el mensaje outbound de éxito se produce **después** del commit, con idempotencia de envío y validación por provider delivery.
- Confirmar que un material solo se emite al lead si el enlace está vigente/autorizado y se conserva su evidencia sin registrar el bearer token.
- Completar escritura verificada de perfil CRM desde Hermes, entrega de materiales y políticas de respuesta ante errores.
- Validar configuración global Staff Superadmin + inglés único y estado aislado entre empresas.

**Resultado del release P04:** listo para revisión/merge del código **apagado**; NO aprobado para activación productiva de acciones ni para reemplazo de LangGraph.
