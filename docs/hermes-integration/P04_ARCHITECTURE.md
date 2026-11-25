# BlackPenguin × Hermes — P04 Operational Tools (Entrega 3)

## Propósito y alcance

**Base:** BlackPenguin `ba65b830acb1fd721465c65afd8985de7309b6bb` (contiene P01 y P23); Hermes demo v13.3.3 `9ac4c8703d28eb3ca39fc762df0dd67c7196e324`.

Hermes será el **único motor conversacional** cuando se habilite la sustitución definitiva. Esta fase P04 agrega un gateway operativo para que Nous Research Hermes pueda consultar disponibilidad y **preparar** decisiones de negocio; un ejecutor separado procesa acciones **solamente en simulaciones**, con comprobaciones y recibos persistentes. No reintroduce etapas LangGraph de interpretación, planificación ni composición. Reutiliza servicios existentes de BlackPenguin para agenda, permisos, aprobaciones, reservas y activos.

### Componentes

| Archivo | Función | Efectos durante inferencia |
|---|---|---|
| `bp_operational_port.py` | `BPOperationalDraftPort`: disponibilidad verificada, elección de hora, recap, borradores de book/cancel/reschedule, descubrimiento de materiales, interés | 0 |
| `bp_operation_receipts.py` | Comprobación de propuestas mostradas, selección y consentimientos ligados a mensajes registrados | 0 |
| `bp_p04_turn.py` | Preparación del turno Hermes de simulación y commit de estado vinculado a salida durable | Solo estado, sin efectos externos |
| `bp_effect_executor.py` | Executor de acción autorizada con `begin_nested`, bloqueo de lead/estado, CAS, revalidación e idempotencia | Exclusivamente sobre registros de **simulación** |
| `bp_operation_models.py` | Recibo inmutable por solicitud (`HermesSalesOperation`) | Persistencia en PostgreSQL |
| `runtime.py` | Permite las herramientas operativas P04 solo en puerto certificado `P04_DRAFT_ONLY` | Sin activar canales reales |
| `bp_state_store.py` | Valida referencias, opciones y recaps contra mensajes realmente entregados | Solo estado |
| `bp_turn.py` | Conserva opciones P04 ya verificadas; P23 sigue con menú deshabilitado | Solo estado |

### Contrato de ejecución

```text
SalesMessage inbound persistido (simulation)
  -> require_scoped_entities (company, project, conversation, lead)
  -> approved BP catalog and lead snapshot (P02)
  -> load Hermes state + bounded verified chat history (P03)
  -> Hermes AIAgent (núcleo P01, herramientas con borradores P04)
  -> preparar respuesta + borrador; NO escribir reuniones ni enlaces
  -> verificar SalesMessage saliente realmente emitido EN simulación
  -> persistir estado y menú / recap verificables (CAS)
  -> un paso EXPLÍCITO e independiente puede invocar execute_p04_simulation_operation
  -> lock/recheck scope + consent + intent + offer + revision
  -> ejecutar efecto SIMULADO y recibo en una transacción
  -> el llamador hace COMMIT o ROLLBACK
```

El paso de ejecución no está conectado a ningún router HTTP ni a los workers de producción. El método `execute_p04_simulation_operation()` no envía la confirmación al cliente; solamente devuelve el resultado verificable tras que la operación termine. El llamador DEBE confirmar la transacción antes de comunicar éxito.

### Herramientas

- `get_available_visit_slots`: llama al motor de disponibilidad `app.modules.sales_crm.scheduling.available_slots`, consulta la disponibilidad de asesores, filtra la zona horaria del proyecto, horizonte de 14 días y horario inicial por hora. **60 minutos ocupados** por slot (45 minutos de visita más 15 de margen). Las búsquedas amplias ofrecen días; una fecha puntual ofrece horas.
- `select_visit_time`: vincula la hora exacta a una opción previamente mostrada al lead. Acepta ordinals solo cuando el menú existió de verdad y su identificador coincide.
- `book_onsite_visit`: redacta solicitud pendiente, con recap completo de unidad/fecha/hora y consentimiento explícito en **turno posterior**. Nunca considera `OK` consentimiento suficiente.
- `cancel_onsite_visit`: registra una solicitud de cancelación **directa** del comprador y huella del `Meeting` activo.
- `reschedule_onsite_visit`: muestra la visita anterior y alternativa; requiere disponibilidad nueva y recap visible antes de reemplazar.
- `get_unit_media`: encuentra activos autorizados, verifica cobertura exacta e integridad con `material_delivery.snapshot`; **no entrega una URL durante inferencia**.
- `track_property_interest`: cambia solo borrador de estado por declaración del comprador.
- `update_lead_profile`: devuelve `CRM_WRITE_DISABLED` (integración de escritura de CRM pendiente). No se ha implementado persistencia comercial libre en esta fase.

### Executor de simulación

`execute_p04_simulation_operation(db, scope, expected_revision, inbound_message_id, ...)` exige **ambas condiciones**: `SalesConversation.channel == 'simulation'` y `Lead.is_demo == True`. También verifica tenant, proyecto, `Lead.consent_status`, no opt-out, no borrado, y que la solicitud corresponda al mensaje real. Reconsulta esos permisos tras obtener bloqueos de filas.

- **Book**: revalida propiedad/ubicación/permiso y disponibilidad desde `create_agent_appointment`; crea `SalesBookingOperation` con `calendar_status='simulation'` y `defer_calendar=True`, sin notificaciones externas.
- **Cancel**: revalida el meeting y su fingerprint antes de marcarlo cancelado y crear `SalesCancellationOperation` (simulación).
- **Reschedule**: nueva cita en la misma transacción, excluyendo la antigua del chequeo de disponibilidad; si falla, se conserva la antigua. Recibos de nuevo booking y replacement con `calendar_status='simulation'`.
- **Material**: emite enlace opaco **de simulación** mediante `asset_share_service.issue`, revalida aprobación y coverage. No se envía por ningún proveedor. El token/bearer URL **no se guarda** en el recibo (un replay no lo revela).
- **Human review**: crea `HumanInterventionCase` con dedupe y pausa la conversación de simulación, sin prometer asignación o callback.

### Seguridad y consistencia

1. Un `TurnScope` validado por BD incluye company/project/conversation/lead en cada consulta; no se acepta el tenant suministrado por el modelo.
2. Las credenciales de OpenRouter, OAuth y mensajería no se serializan en estado Hermes.
3. Las opciones y recaps deben estar asociadas a mensajes salientes realmente registrados y mostrar sus etiquetas exactas; resultados ocultos de herramientas no cuentan como oferta.
4. Solo un mensaje inbound posterior, explícito y del mismo lead puede aprobar la reserva; la disponibilidad se revalida justo antes de insertar.
5. Persistencia mediante revisión CAS + recibo de operación con hash del payload y `request_id` único; reintentos no ejecutan el efecto dos veces.
6. Las operaciones no escriben en mensajería, proveedores SMS/WhatsApp, Google Calendar ni servicios externos.
7. Se usa `sandbox()` de infraestructura de BP y sus servicios transaccionales, **no** el coordinador o el clasificador LangGraph.

### Restricciones conocidas

- La ejecución se limita a **simulación**. P04 NO constituye una prueba de reservas/Google Calendar reales ni habilita los canales productivos.
- En tests SQLAlchemy se usó SQLite y stubs para los efectos que dependen de calendario y correo. Faltan ensayos en PostgreSQL con datos autorizados de staging.
- El port operativo no guarda el perfil CRM. La traducción de categorías y propiedades entre la demo y el sistema real debe revisarse mediante casos E2E, incluyendo cancelación y reschedule.
- El SDK Hermes real, el modelo OpenRouter y la infraestructura de workers siguen requiriendo validaciones en el ambiente de integración.
- **No hay ruta integrada aún que llame automáticamente al executor tras un turno**. Debe conectarse únicamente después de que P5–P7 resuelvan el orden de commit, efectos y el sistema de mensajería.
- El prompt de Hermes es global, de Staff Superadmin, con inglés único; esta fase no introduce configuraciones particulares de empresa/proyecto.

### Próximas entregas

P5+P6: integración Angular 21 y Staff Superadmin. P7: pruebas E2E con SDK real, PostgreSQL, consistencia, concurrencia y proveedores; pruebas de seguridad y mediciones. P8: cambio único del sales worker a Hermes y retirada de la orquestación LangGraph.
