# Visita sin segmento

[Volver a la guía del agente](../../README.md) · [Abrir evidencia técnica JSON](visita-sin-segmento__unknown-a__sales-compact-repair-1__fallido.json)

**Conversación sintética ejecutada en el servidor.** Los mensajes se conservan en su idioma original. La explicación resume campos estructurados y controles exportados; no representa razonamiento privado del modelo ni una explicación generada posteriormente por otro LLM.

| Dato | Evidencia |
|---|---|
| Caso / corrida | `unknown_A` / `sales-compact-repair-1` |
| Resultado automático original | Fallida: revisar los puntos señalados |
| Modelo / configuración | `openai/gpt-4o-mini` / 8 |
| Visitas registradas / turnos | 0 / 3 |
| Costo | El reporte lo agrega por corrida; no se inventa un importe por conversación. |

**Cómo repetirla:** usar una company y un project de prueba con información aprobada coherente; sustituir nombres, recursos y horarios por los vigentes. Una aprobación histórica no garantiza estabilidad con nuevos mensajes o entrega por WhatsApp/SMS. Las fechas y recursos de este laboratorio no son una oferta real.

**Calidad del diálogo:** NOT_EVALUATED. **No hay aprobación integral del diálogo.** Los checks originales y nombres de archivo son históricos. Aprobarlos no certifica relevancia, fluidez ni todo el diálogo. Una revisión favorable solo cubre los comportamientos que describe.

**Qué falló en esta corrida:** dialogue_reached_terminal_outcome, expected_booking_outcome, turn_completed. El estado original se conserva, incluso si se corrigió después.

## Turno 1

**Lead sintético**

> My budget is 500,000 USD, paying cash. What can you tell me about Ridge Townhome?

**Qué interpretó el agente — registro estructurado**

Solicitó disponibilidad sobre «Ridge Townhome»; Declaración registrada de presupuesto: «500000 USD» (declared); Declaración registrada de forma de pago: «cash» (declared); Confianza registrada: 0.99 (no es una probabilidad calibrada).

**Cómo procedió — evidencia disponible**

La composición fue aceptada dentro de las opciones de evidencia autorizadas.

**Respuesta del agente**

> Here are the property options I can confirm:
> 
> 1. Ridge Townhome — 3 bedrooms, 2.5 bathrooms, 165 m². Published prices start at 460,000.00 USD. Last confirmed quantity: 4. Synthetic property for testing. Only the listed features are confirmed. Features: Private patio.
> 
> You are considering an outright purchase, without financing.
> 
> What would you like to know next about the property?

## Turno 2

**Lead sintético**

> I would like to arrange an in-person visit to Ridge Townhome. Any available time in the next seven days works for me. Please use the project timezone.

**Qué interpretó el agente — registro estructurado**

No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.

**Cómo procedió — evidencia disponible**

El turno registró un error de procesamiento: understanding_validation_failed.
Controles sin aprobar: turn_completed.

**Respuesta del agente**

> Would you like me to connect you with the sales team to help with your question?

## Turno 3

**Lead sintético**

> I would like to arrange an in-person visit to Ridge Townhome. Any available time in the next seven days works for me. Please use the project timezone.

**Qué interpretó el agente — registro estructurado**

No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.

**Cómo procedió — evidencia disponible**

El turno registró un error de procesamiento: understanding_validation_failed.
Controles sin aprobar: turn_completed.

**Respuesta del agente**

> Would you prefer to continue here or speak with the sales team?

## Resultado y respaldo

Visitas registradas en el laboratorio: **0**. Consultar el JSON para recursos, equipo, interpretación completa, controles e identificadores. No confundir la cita del laboratorio con un evento confirmado en Calendar externo.

[Abrir JSON de esta conversación](visita-sin-segmento__unknown-a__sales-compact-repair-1__fallido.json)
