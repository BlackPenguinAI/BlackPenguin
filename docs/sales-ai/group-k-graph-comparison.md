# Grupo K — Contraste funcional de los tres recorridos objetivo

Se contrastan (1) procesamiento de cada mensaje, (2) evolución de la conversación comercial,
y (3) consulta o modificación de una cita. Son responsabilidades funcionales; no equivalen a
los modos legacy/shadow/active. No se afirma que existan tres grafos LangGraph compilados.
Los diagramas originales completos no están en el repositorio ni en los adjuntos disponibles;
esta comparación aplica los requisitos del plan y sus tres objetivos recuperados. No certifica
igualdad de cada nodo/arista con una definición Mermaid original que no pudo recuperarse.

| Recorrido | Implementación contrastada | Evidencia automatizada | Límite de aceptación |
|---|---|---|---|
| Mensaje: ingreso, ámbito, controles e idioma antes de interpretar | `provider_router.py`, `conversation_scope.py`, `language_policy.py`, `active_service.py` | B: idioma/contexto; J: moderación y ámbito; K: callbacks firmados SMS/WA | No usa números ni firmas de producción. |
| Mensaje: interpretación estricta, reparación, referencias y tareas acotadas | `understanding_service.py`, `reference_resolution.py`, `dialogue_orchestrator.py` | D: dependencias, límites y referencias; recuperación de comprensión existente | El modelo real no se ejecutó sin credencial. |
| Mensaje: resultados verificados, composición, validación final, persistencia y entrega | `commercial_composer.py`, `active_service.py`, `live_service.py` | E: composición/materiales; K: reinicio de sesión y fallo de despacho | Aceptación por proveedor simulada no equivale a entrega real. |
| Conversación: interés actual, preferencias y etapas como orientación | `lead_profile.py`, `turn_memory.py`, `turn_configuration.py`, `dialogue_store.py` | C/D/E: perfil, cambio de interés y guía publicada | La calidad comercial requiere evaluación real y revisión humana. |
| Conversación: materiales, invitación prudente, rechazo y regreso posterior | `commercial_composer.py`, `first_booking.py`, `continuity_policy.py` | T06–T10, T14/T16/T21 en la matriz de cobertura | No se certifica contenido de PDF/fotos reales a partir de metadatos. |
| Conversación: moderación gradual, baja, control humano y revisión acotada | `moderation.py`, `conversation_review.py`, `service.py` | J: aviso aceptado, reincidencia, falsos positivos y consentimiento | Los patrones de moderación son acotados; no garantizan reconocer toda expresión. |
| Cita: consultar verdad persistida separada de propiedad consultada | `appointment_context.py`, `operational_context.py` | C/F/J y recorrido conectado K | No se consulta Calendar real. |
| Cita: opciones vigentes, selección, resumen exacto y confirmación | `first_booking.py`, `sales_crm/scheduling.py` | F y K: espera → aviso → reserva única | Contención PostgreSQL real pendiente en este entorno. |
| Cita: comparar reemplazo, conservar original, confirmar y reintentar efectos | `reschedule_service.py`, `reschedule_models.py` | G y K: cambio + nueva sesión + despacho fallido | No se certifica entrega exactamente una vez a través de una red externa. |
| Cita: cancelar con confirmación; continuar conversando; esperar con permiso | `cancellation_service.py`, `wait_service.py` | H/I y K: reserva → consulta B → cambio → cancelación → nueva consulta | Son operaciones y proveedores aislados, no aceptación por canales reales. |

Los nombres de archivo sin directorio pertenecen a `backend/app/modules/sales_agent/`.
`group_k_coverage.json` enlaza T01–T26 con funciones de prueba reales. Sus entradas dicen
`AUTOMATED_PARTIAL_NOT_FINAL_ACCEPTANCE`: ni una referencia de prueba ni una regresión verde
sustituyen la evaluación del modelo, contención real, revisión comercial o aceptación por canales.

La separación importante se conserva durante el recorrido conectado: el permiso de conversar
no cambia por reservar/cancelar; consultar Loft no modifica la reserva Studio; un cambio necesita
su propia confirmación y una baja impide reanudar aunque un incidente se marque falso positivo.
