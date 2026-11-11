# Agente de ventas IA: funcionamiento y laboratorio

[Volver al README del repositorio](../../README.md)

Esta guía explica el flujo actual y cómo se ha evaluado con empresas, propiedades, vendedores y leads ficticios. Está dirigida a producto, operaciones y desarrollo. Los JSON enlazados contienen los datos completos; no hace falta leer código para recorrer la guía.

**Objetivo comercial:** resolver consultas con información aprobada y facilitar una visita presencial. El agente no cobra, separa inmuebles, aprueba créditos ni cierra una venta. El equipo humano atiende la visita y el cierre posterior.

| Quiero entender… | Abrir |
|---|---|
| Qué hace el agente y cómo decide | [Funcionamiento y diagramas](01-como-funciona/README.md) |
| Qué empresa, propiedades, leads y vendedores se usan | [Datos de prueba y sus JSON](02-datos-de-prueba/README.md) |
| Qué situaciones probamos y cómo iteramos | [Casos y diseño experimental](03-casos-de-prueba/README.md) |
| Qué dijeron los leads y qué respondió el agente | [Conversaciones y evaluación](04-conversaciones/README.md) |
| Cómo cambiaron las métricas y qué falta | [Resultados y gráficas](05-resultados-y-mejoras/README.md) |
| Cómo reproducir y actualizar la evidencia | [Instrucciones técnicas](06-como-ejecutar-las-pruebas/README.md) |

## Estado de la evidencia

Última corrida de servidor incorporada: **Repair 4**, commit `ffef47639bc01fdf776a8ee6b0fdbc17863b2d40`, modelo `openai/gpt-4o-mini`, configuración publicada 8. Pasaron dos de tres conversaciones y se crearon dos de dos visitas esperadas en SQLite aislado. La tercera tuvo un rechazo de composición por orden y un timeout de reparación. No hubo escrituras ni contacto con leads de producción.

La corrección siguiente (Repair 5) queda **pendiente de evaluación con el modelo publicado**. Las pruebas locales con HTTP simulado no se presentan como corridas del servidor. Esta guía es una fotografía versionada; el JSON de cada corrida conserva su commit y configuración.

## Cómo interpretar los resultados

- **Aprobado automáticamente:** pasó los controles de esa versión, no implica una revisión humana favorable.
- **Revisado favorablemente:** se leyó esa transcripción concreta y se anotó su alcance. No certifica otros diálogos.
- **Fallido o incompleto:** se conserva la evidencia para explicar qué falta; no se elimina del historial.
- **Visita confirmada:** se persistió una cita en el laboratorio después de selección y confirmación. No significa evento real en Google Calendar ni entrega por WhatsApp/SMS.

No existe todavía una medida universal de “calidad del agente”. Mostramos resultados observados por conjunto de casos, sin promedios ponderados, curvas suavizadas ni predicciones.
