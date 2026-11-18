# P0 — Conversación real: continuidad, control humano y composición

**Base:** `3e554d715e6a5e41d6fa583d13d11d2995683de3` (scoring hotfix).
**Alcance:** WhatsApp y SMS comparten `active_service`; este parche cambia el flujo común, sin cambiar webhooks, Telnyx, reservas, Calendar ni persistencia del catálogo.

## Incidentes reproducibles de la conversación real (redactados)

| Entrada actual | Contexto previo entregado | Resultado requerido |
|---|---|---|
| `Yes` | Invitación a consultar opciones de visita para la propiedad seleccionada | Interpretación determinista de **búsqueda** de visita; no reserva, no consentimiento final |
| `Madison` | Oferta de horarios para *Madison* vigente | Mantener la visita y consultar horarios nuevamente; no selección de hora ni confirmación de reserva |
| `Yes` | Tres horarios ofrecidos, sin elección exacta | Sin selección automática de horario |
| `What happened?` | Fallo de procesamiento previo | Responder brevemente sobre el fallo anterior, sin ofrecer transferencia humana ni exponer trazas |
| Primera solicitud humana explícita | Conversación comercial normal | Ofrecer seguir atendiendo y preguntar si insiste en revisión humana |
| `Yes` | Pregunta de revisión humana explícita y entregada del backend | Registrar intervención `HUMAN_REQUESTED`, pausar IA, notificar a la compañía |
| `Yes` | Pregunta de derivación inventada por el modelo | No pausar ni registrar intervención |
| Solicitud de credenciales ajenas, amenaza validada | Incidente grave | Conservar protección inmediata, sin exigir doble confirmación |
| Respuesta factual del modelo lenta | Composición | Presupuesto máximo acotado de 12 s por llamada; respuesta de respaldo solo con evidencia verificada |

## Tests gratuitos

```bash
cd /app
python -m tools.sales_ai.p0_live_selftest  # incluye test_sales_delivery3_contact_closing.py
python -m pytest -q tests/test_sales_p1a_mixed_human.py tests/test_sales_p1c1.py \
  tests/test_sales_booking_refinement.py tests/test_sales_continuity_gaps.py
```

**Control manual:** la notificación se encola a través del servicio ya existente de gobernanza; las pruebas unitarias no demuestran entrega final al administrador. Verificar el procesador de `notification_outbox` y la UI de `human_intervention_cases` con una cuenta de prueba.

## Prueba controlada extremo a extremo (solo tras CI, con números autorizados)

1. WhatsApp: saludo → catálogo → propiedad → brochure/galería → invitación de visita → `Yes` → oferta de horarios → nombre de propiedad → oferta actualizada → selección exacta → resumen → confirmación. Comprobar que **no existe una segunda cita** sin confirmación final.
2. WhatsApp: pregunta sobre fallo, consulta de precio y una consulta de visita. No debe producir derivación humana.
3. WhatsApp: solicitud humana explícita → primera confirmación → `Yes`. La IA debe pausarse, registrar caso `HUMAN_REQUESTED` y encolar notificación con `company_id` correspondiente.
4. SMS: replicar los mismos pasos con lead y teléfono de prueba independientes. Validar fragmentación SMS, entrega e idempotencia de mensajes.
5. Fallo de proveedor simulado: timeout de composición, respuesta respaldada solo por evidencia, sin perder autorización o la última oferta.
6. En ambos canales: verificar errores del último `AgentRun`, `graph.status`, `metadata.composition`, consultas efectivas, `notification_outbox`, estado de `sales_conversations.is_paused` y `human_intervention_cases` (solo lectura).

**No reutilizar IDs ni teléfono reales en fixtures.** Las citas de prueba y los mensajes externos deben quedar explícitamente autorizados. Un estado `completed` del grafo, por sí solo, no acredita calidad comercial: comprobar tareas, respuestas y efectos.

## Limitaciones

- Los casos `Yes` y `Madison` son continuaciones **muy restringidas** de la oferta inmediatamente anterior, no clasificadores generales. La propuesta de cita y su confirmación siguen siendo pasos separados, con revalidación de alcance, vendedor, calendario y consentimiento.
- Los timeouts a 8 s de la batería real justifican probar 12 s; no garantizan mejora hasta comparar latencia y `safe_fallback` en llamadas nuevas.
- El identificador `S09_HANDOFF` sigue representando la etapa comercial de cita confirmada; **no se cambia automáticamente** por control humano.
- Este diferencial **no borra ni repara automáticamente tareas históricas** de una conversación ni modifica una reserva existente.
