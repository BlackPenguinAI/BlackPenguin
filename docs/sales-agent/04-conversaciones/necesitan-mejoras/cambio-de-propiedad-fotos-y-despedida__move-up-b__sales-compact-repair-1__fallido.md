# Cambio de propiedad fotos y despedida

[Volver a la guía del agente](../../README.md) · [Abrir evidencia técnica JSON](cambio-de-propiedad-fotos-y-despedida__move-up-b__sales-compact-repair-1__fallido.json)

**Conversación sintética ejecutada en el servidor.** Los mensajes se conservan en su idioma original. La explicación resume campos estructurados y controles exportados; no representa razonamiento privado del modelo ni una explicación generada posteriormente por otro LLM.

| Dato | Evidencia |
|---|---|
| Caso / corrida | `move_up_B` / `sales-compact-repair-1` |
| Resultado automático original | Fallida: revisar los puntos señalados |
| Modelo / configuración | `openai/gpt-4o-mini` / 8 |
| Visitas registradas / turnos | 0 / 4 |
| Costo | El reporte lo agrega por corrida; no se inventa un importe por conversación. |

**Cómo repetirla:** usar una company y un project de prueba con información aprobada coherente; sustituir nombres, recursos y horarios por los vigentes. Una aprobación histórica no garantiza estabilidad con nuevos mensajes o entrega por WhatsApp/SMS. Las fechas y recursos de este laboratorio no son una oferta real.

**Qué falló en esta corrida:** cash_preference_persists, declared_budget_persists, property_switch_reflected, requested_material_delivered, segment_evidence_from_own_initial_declaration, segment_matches_declared_motivation, turn_completed. El estado original se conserva, incluso si se corrigió después.

## Turno 1

**Lead sintético**

> I want to move from my current small home to a larger home. My budget is 400,000 USD, paying cash. Please show me Cedar Studio.

**Qué interpretó el agente — registro estructurado**

No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.

**Cómo procedió — evidencia disponible**

El turno registró un error de procesamiento: understanding_validation_failed.
Controles sin aprobar: turn_completed, segment_matches_declared_motivation, segment_evidence_from_own_initial_declaration, declared_budget_persists, cash_preference_persists.

**Respuesta del agente**

> Would you like me to connect you with the sales team to help with your question?

## Turno 2

**Lead sintético**

> Actually I prefer Cedar Loft instead. Please send its photos.

**Qué interpretó el agente — registro estructurado**

No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.

**Cómo procedió — evidencia disponible**

El turno registró un error de procesamiento: understanding_validation_failed.
Controles sin aprobar: turn_completed, segment_matches_declared_motivation, segment_evidence_from_own_initial_declaration, declared_budget_persists, cash_preference_persists.

**Respuesta del agente**

> Would you prefer to continue here or speak with the sales team?

## Turno 3

**Lead sintético**

> I do not want a visit yet.

**Qué interpretó el agente — registro estructurado**

Excluyó visita; Restricciones registradas: visita; Confianza registrada: 0.99 (no es una probabilidad calibrada).

**Cómo procedió — evidencia disponible**

La composición fue aceptada dentro de las opciones de evidencia autorizadas.
Controles sin aprobar: segment_matches_declared_motivation, segment_evidence_from_own_initial_declaration, declared_budget_persists, cash_preference_persists.

**Respuesta del agente**

> Is there another property question I can help with?

## Turno 4

**Lead sintético**

> No other questions, thank you. Goodbye.

**Qué interpretó el agente — registro estructurado**

Confianza registrada: 1.0 (no es una probabilidad calibrada).

**Cómo procedió — evidencia disponible**

Controles sin aprobar: segment_matches_declared_motivation, segment_evidence_from_own_initial_declaration, declared_budget_persists, cash_preference_persists.

**Respuesta del agente**

> You're welcome. Thank you for your interest and have a good day. You can message again whenever another question comes up.

## Resultado y respaldo

Visitas registradas en el laboratorio: **0**. Consultar el JSON para recursos, equipo, interpretación completa, controles e identificadores. No confundir la cita del laboratorio con un evento confirmado en Calendar externo.

[Abrir JSON de esta conversación](cambio-de-propiedad-fotos-y-despedida__move-up-b__sales-compact-repair-1__fallido.json)
