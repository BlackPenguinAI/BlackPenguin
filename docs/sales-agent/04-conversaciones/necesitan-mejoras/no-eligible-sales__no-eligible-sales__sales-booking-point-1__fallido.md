# No eligible sales

[Volver a la guía del agente](../../README.md) · [Abrir evidencia técnica JSON](no-eligible-sales__no-eligible-sales__sales-booking-point-1__fallido.json)

**Conversación sintética ejecutada en el servidor.** Los mensajes se conservan en su idioma original. La explicación resume campos estructurados y controles exportados; no representa razonamiento privado del modelo ni una explicación generada posteriormente por otro LLM.

| Dato | Evidencia |
|---|---|
| Caso / corrida | `no_eligible_sales` / `sales-booking-point-1` |
| Resultado automático original | Fallida: revisar los puntos señalados |
| Modelo / configuración | `openai/gpt-4o-mini` / 8 |
| Visitas registradas / turnos | 0 / 2 |
| Costo | El reporte lo agrega por corrida; no se inventa un importe por conversación. |

**Cómo repetirla:** usar una company y un project de prueba con información aprobada coherente; sustituir nombres, recursos y horarios por los vigentes. Una aprobación histórica no garantiza estabilidad con nuevos mensajes o entrega por WhatsApp/SMS. Las fechas y recursos de este laboratorio no son una oferta real.

**Calidad del diálogo:** NOT_EVALUATED. **No hay aprobación integral del diálogo.** Los checks originales y nombres de archivo son históricos. Aprobarlos no certifica relevancia, fluidez ni todo el diálogo. Una revisión favorable solo cubre los comportamientos que describe.

**Qué falló en esta corrida:** interpretation_accepted, unavailability_explained. El estado original se conserva, incluso si se corrigió después.

## Turno 1

**Lead sintético**

> I am interested in Bay Residence at Harbor Gardens and would like to book an in-person visit. My budget is 900,000 USD, paying cash. Any time in the next seven days works; please use the project timezone.

**Qué interpretó el agente — registro estructurado**

No se exportó una interpretación válida para este turno. No se infiere a partir de la respuesta.

**Cómo procedió — evidencia disponible**

El turno registró un error de procesamiento: understanding_validation_failed.
Controles sin aprobar: interpretation_accepted.

**Respuesta del agente**

> Would you like me to connect you with the sales team to help with your question?

## Turno 2

**Lead sintético**

> Understood, thank you. I will keep an eye out for new availability. Please do not book anything or set up an alert now.

**Qué interpretó el agente — registro estructurado**

Restricciones registradas: visita, visita; Confianza registrada: 0.99 (no es una probabilidad calibrada).

**Cómo procedió — evidencia disponible**

La composición fue aceptada dentro de las opciones de evidencia autorizadas.

**Respuesta del agente**

> You can message here if another question comes up.

## Resultado y respaldo

Visitas registradas en el laboratorio: **0**. Consultar el JSON para recursos, equipo, interpretación completa, controles e identificadores. No confundir la cita del laboratorio con un evento confirmado en Calendar externo.

[Abrir JSON de esta conversación](no-eligible-sales__no-eligible-sales__sales-booking-point-1__fallido.json)
