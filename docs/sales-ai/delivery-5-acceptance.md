# Delivery 5 — 64-case local evidence

Scripted regression: 63 PASS, 0 FAIL, 1 NOT_RUN. Case 57 requires observed real-model/end-to-end quality.
Real model, actual SMS/WhatsApp and production acceptance remain NOT_RUN for this work.
Seven PostgreSQL races are included; local socket restrictions prevented execution. The candidate deployment runs them in a disposable internal Docker network before stopping production.

| ID | Escenario | Regresión | Modelo real | SMS / WhatsApp |
|---|---|---|---|---|
| 1 | Datos mínimos de Meta y alta manual | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 2 | Datos comerciales compartidos espontáneamente | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 3 | Edad y ocupación voluntarias | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 4 | Otros detalles personales voluntarios y pertinentes | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 5 | No interrogar por información privada; respetar rechazo | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 6 | Correcciones y contradicciones del perfil | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 7 | Memoria futura y separación por ámbito | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 8 | Variantes para catálogo e inventario | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 9 | Errores de escritura y ausencia de ? | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 10 | Sinónimos property/units/houses/apartments | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 11 | Solicitudes concatenadas y AND/OR/NOT | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 12 | Referencias y sí/no contextual | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 13 | Inglés de entrada/salida y configuración multilingüe | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 14 | Respuesta directa, natural y no repetitiva | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 15 | Empatía ante asuntos personales y retorno al tema | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 16 | Saludos, agradecimientos, despedidas y no por ahora | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 17 | Catálogo conciso y disponibilidad verificada | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 18 | Más información en texto sobre una propiedad | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 19 | Elegir y conservar interés actual | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 20 | Cambiar propiedad sin cambiar una reserva existente | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 21 | Comparación general de dos o más propiedades | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 22 | Comparación por baños, dormitorios, cocina o features | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 23 | Superlativos y recomendación fundada | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 24 | Precios, moneda, promociones, financiación y entrega | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 25 | Amenidades, ubicación y datos no confirmados | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 26 | Fotos sin propiedad seleccionada | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 27 | Planos sin propiedad seleccionada | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 28 | Fotos o planos con propiedad ya elegida | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 29 | Fotos en PDF; planos como imagen o PDF | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 30 | Links para SMS y WhatsApp; no adjuntos necesarios | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 31 | Ofrecer planos adicionales después de fotos y viceversa | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 32 | Un PDF cubre varias necesidades de la misma propiedad | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 33 | Un archivo vinculado a varias tipologías/unidades | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 34 | Documento/galería accesible para el lead y revisiones posteriores | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 35 | Falta material solicitado | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 36 | Ver la propiedad vs ver más información vs visitar | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 37 | Restricciones explícitas y ofertas vencidas | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 38 | Despedida breve por inactividad | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 39 | Cadencias comerciales y avisos de disponibilidad | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 40 | Mensajes recibidos durante pausa | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 41 | Administrador escribe y luego Resume | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 42 | Resume sin mensaje humano | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 43 | Pedido de humano o callback | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 44 | Motivo de pausa, atención y falso positivo en espejo | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 45 | Insulto dirigido: advertir antes de pausar | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 46 | Desescalada y resistencia comercial legítima | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 47 | Amenazas concretas y extracción privada | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 48 | Peticiones ajenas, búsquedas web o ejecutar código | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 49 | Citas/negaciones de lenguaje hostil | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 50 | Baja, consentimiento, horarios, canal y Demo | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 51 | Company/Project/lead aislados y recursos autorizados | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 52 | Primera cita, horarios y confirmación | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 53 | Consultar, cambiar o cancelar citas existentes | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 54 | FIFO, duplicados y fallos de entrega | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 55 | Interpretación inválida y reparación | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 56 | Activación y configuración efectiva coherentes | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 57 | Calidad real del modelo y aceptación end-to-end | NOT_RUN | NOT_RUN | NOT_RUN / NOT_RUN |
| 58 | Saludo inicial contextual y captura de campaña | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 59 | Cualificación comercial progresiva y no obligatoria | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 60 | Tour virtual y mapa como recursos | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 61 | Scoring interno y temperaturas hot/warm/cold | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 62 | Segmentación y estrategias publicadas | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 63 | Objeciones, quejas y excepciones legales/comerciales | PASS | NOT_RUN | NOT_RUN / NOT_RUN |
| 64 | Handoff con resumen útil para Sales | PASS | NOT_RUN | NOT_RUN / NOT_RUN |

The JSON report links each local result to actual pytest nodes and source hashes. Passing scripted tests or queue health does not prove natural-language quality, device delivery or commercial acceptance.
