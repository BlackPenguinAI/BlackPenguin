# Sales Agent · funcionamiento, experimentos y mejoras

[Inicio del repositorio](../../README.md) · [Datos JSON](02-datos-de-prueba/) · [Conversaciones](04-conversaciones/) · [Evidencia de corridas](05-resultados-y-mejoras/)

**Corte documental: 11/11/2026.** Se reúne el trabajo del ciclo reciente con data sintética: **18 corridas del servidor, 122 conversaciones ejecutadas y 47 IDs de escenario distintos por suite**. Las repeticiones son parte del trabajo, no escenarios adicionales. El último resultado real es Repair 6: **2/3 conversaciones aprobadas y 2/2 visitas confirmadas**. El cambio de propiedad y su galería ya aprobaron; primera compra falló por evidencia histórica reutilizada y tiempos de espera. Todavía no se considera estable.

La guía usa bloques con el mismo propósito: **qué se hizo → cómo funciona → qué evidencia hay → dónde están sus archivos**. Toda la explicación está aquí; los enlaces internos abren datos, código o carpetas de respaldo. Las referencias externas justifican la metodología, no sustituyen la evidencia del proyecto.

[1. Producto](#1-producto-y-rutas) · [2. LLM/backend](#2-llm-y-backend) · [3. Datos](#3-datos-sintéticos) · [4. Experimentos](#4-diseño-de-los-experimentos) · [5. Afinamiento](#5-qué-se-modifica-al-afinar) · [6. Evolución](#6-historia-y-evolución-medida) · [7. Diálogos](#7-conversaciones-para-repetir) · [8. Consumos](#8-consumo-real-y-saldo-de-openrouter) · [9. Referencias](#9-referencias-y-fundamento) · [10. Trabajo actual](#10-trabajo-actual) · [11. Trabajo futuro](#11-trabajo-futuro)

## 1. Producto y rutas

**Propósito.** Informar con el conocimiento aprobado y ayudar al lead a decidirse por una visita. El personal humano atiende esa visita y cierra la venta. En el chat no se cobra, separa un inmueble ni aprueba un crédito. “Cash” se interpreta como compra de contado, no billetes físicos ni fondos verificados.

```mermaid
stateDiagram-v2
    [*] --> Consulta
    Consulta --> Horarios: solicita visita y hay disponibilidad
    Horarios --> Resumen: elige opción vigente
    Resumen --> Cita: confirma y backend revalida
    Resumen --> Consulta: rechaza o cambian los datos
    Cita --> [*]
```

**Rutas del producto.** El flujo actual es `sales-current/1.0`; los flags históricos ya no seleccionan otro motor. Esto conserva autorización, aislamiento y control humano: una conversación pausada no debe responder automáticamente.

| Ruta/canal | Función | Acceso o condición |
|---|---|---|
| `/app/agent` | Conversaciones, alta y control humano | `admin`, `assistant`, `mkt`, según company/project. |
| WhatsApp/SMS entrante | Conduce al coordinador actual | Canal configurado, lead autorizado y estado activo. |
| `/app/schedule` | Disponibilidad y citas | `admin`, `assistant`, `sales`, con su alcance. |
| `/app/projects/:id/onboarding` | Conocimiento aprobado del project | `admin`, `assistant`; alimenta al vendedor. |
| `/admin/ai-settings` y `/admin/messaging-settings` | Modelo publicado y mensajería | `superadmin`; configuración no equivale a entrega exitosa. |
| Laboratorio CLI | El mismo core sin transporte | SQLite desechable; no escribe leads/citas productivos. |

**Alcance probado.** Información, contado/financiación publicada, PDF, visitas, rechazo, petición humana y retoma en la misma corrida. Cambio de propiedad/fotos sigue pendiente de confirmación live. La falta de horarios no debe inventar alertas; cancelación y reagendamiento no se acreditan con esta batería. [Rutas UI](../../frontend/src/app/app.routes.ts) · [API](../../backend/app/modules/sales_agent/router.py).

## 2. LLM y backend

**Modelo observado en el servidor:** `openai/gpt-4o-mini` mediante OpenRouter, configuración publicada **8**. Esa versión corresponde a settings, no a pesos del modelo. No hay evidencia aquí de un snapshot fechado del proveedor ni de entrenamiento propio. El lead actual está guionado y no usa otro LLM; el juez LLM está desactivado.

```mermaid
sequenceDiagram
    participant Lead
    participant Backend
    participant LLM
    participant Datos
    Lead->>Backend: Mensaje de su project
    Backend->>Backend: Permisos y continuidad
    Backend->>LLM: Interpretar mensaje y contexto
    LLM-->>Backend: Solicitudes, preferencias y evidencia
    Backend->>Datos: Consultas autorizadas tras validar
    Datos-->>Backend: Hechos, recursos u horarios
    Backend->>LLM: Elegir bloques y continuación permitidos
    LLM-->>Backend: Selección estructurada
    Backend->>Backend: Validar, registrar y ejecutar
    Backend-->>Lead: Respuesta y enlaces aprobados
```

| Paso | Responsable | Regla principal |
|---|---|---|
| Interpretación | LLM | Identifica intención y sujeto con evidencia del mensaje actual. |
| Validación y memoria | Backend | Comprueba datos, conserva preferencias y no inventa consentimiento. |
| Plan y herramientas | Backend | Resuelve propiedad/unidad/recurso dentro de la company y project. |
| Composición | LLM / backend | El modelo selecciona variantes de evidencia; Repair 7 presenta directamente un comprobante de cita único ya validado. No escribe hechos libres. |
| Compartir/agendar/enviar | Backend | Verifica permisos y efectos; seleccionar horario solo prepara el resumen. |

**Límites.** Hay reparaciones acotadas; no se repite indefinidamente. Algunos turnos usan texto del backend, por lo que turno y llamada son unidades distintas. Los errores internos no se narran al lead. En esta entrega el prompt nuevo es `sales-understanding-prompt/2.28`; el contrato de entrada es `sales-interpretation-input/2.0` y el compositor `sales-commercial-composer/1.0` [R1–R3]. [Coordinador](../../backend/app/modules/sales_agent/active_service.py) · [Interpretación](../../backend/app/modules/sales_agent/understanding_service.py).

## 3. Datos sintéticos

**Se confeccionó una company**, SYNTHETIC - Penguin Sales Laboratory, con tres projects aprobados y seis tipos de propiedad. Las fichas tienen country US, timezones de proyecto, direcciones ficticias y pago publicado de contado/financiación bancaria, sin tasa, inicial o rentabilidad garantizada inventada.

| Project / timezone | Propiedad | Precio USD | Disponibles | Galería / PDF |
|---|---|---|---|---|
| Harbor Gardens / New York | Bay Residence | 780.000 | 3 | Ambos |
| Cedar Heights / Chicago | Cedar Loft | 325.000 | 5 | Galería |
| Cedar Heights / Chicago | Cedar Studio | 210.000 | 2 | PDF |
| Sierra Commons / Denver | Ridge Townhome | 460.000 | 4 | Ninguno |
| Sierra Commons / Denver | Summit Villa | 620.000 | **0** | Ambos |
| Sierra Commons / Denver | Valley Apartment | **Desconocido** | **Desconocido** | Ninguno |

**Leads actuales: siete segmentos y uno desconocido.** Son perfiles ficticios con una guía de motivación y objetivos, no personas contactadas. En las corridas actuales sus mensajes los conduce un guion; no se paga otro LLM para representar al lead.

| Lead sintético | Segmento / motivación | Qué permite comprobar |
|---|---|---|
| Emma Torres | Primera vivienda | Explicar la propiedad, entregar PDF y guiar hacia una visita. |
| Daniel Brooks | Cambiar a una vivienda mayor | Respetar cambios de propiedad, fotos y rechazo temporal de visita. |
| Sofia Reed | Reubicación por trabajo | Responder ubicación y ofrecer solo vendedores habilitados. |
| Martin Vega | Cambiar a una vivienda menor | Entregar material correcto y reconocer recursos ausentes o propiedades agotadas. |
| Lucas Chen | Inversión para alquiler | Informar sin inventar rentabilidad, precios o inventario. |
| Valeria Cruz | Valorización y posterior reventa | Explicar condiciones publicadas sin cobrar ni reservar por chat. |
| Adrian Park | Diversificación de inversiones | Comparar opciones y gestionar disponibilidad de visitas. |
| Alex Rivera | Motivación desconocida, sin segmento | Ayudar y agendar sin atribuir una motivación no declarada. |

**Total: ocho perfiles**, con variantes A/B que conforman 16 escenarios. Edad y ocupación no están definidas. Cada variante fija presupuesto, restricciones y resultado esperado; el segmento se verifica desde lo dicho, no se precarga como respuesta correcta.

**Vendedores.** Cinco roles por escenario: candidato, asignado a otro project, ninguno, inactivo y no acepta citas. El candidato puede abarcar todos, dos, uno o ningún project de su company y puede no tener slots. Son 80 identidades para 16 escenarios, no 80 elegibles a la vez. Se reconstruyen asignaciones activas por caso. El snapshot documental tiene bloques 15:00–18:00 UTC a +2/+3/+4 días; las corridas calculan sus propias fechas.

```json
{
  "case": "first_time_A", "goal": "booked", "access": "single",
  "budget": 300000, "cash": true, "material": "pdf"
}
```

**Organización.** Empresa → projects → propiedades → recursos; vendedor → company + asignaciones + slots; lead → perfil + escenario + conversación. PDFs e ilustraciones son reales como archivos, pero ficticios como oferta. Un PDF no acredita fotos/planos; los enlaces solo viven dentro del laboratorio.

[Empresa y propiedades JSON](02-datos-de-prueba/empresa-y-proyectos/) · [Perfiles de leads](02-datos-de-prueba/leads/) · [Vendedores, asignaciones y horarios](02-datos-de-prueba/vendedores-y-horarios/) · [16 guiones](03-casos-de-prueba/casos-guionados.json).

## 4. Diseño de los experimentos

**Inicio: lead LLM.** Tres perfiles por project —nuevo comprador, materiales de una propiedad y continuidad de contado a financiación—: nueve diálogos, hasta seis turnos del lead. En Lab 2 y 3 ambos participantes usaron `gpt-4o-mini`. El comprador veía su guía y la conversación pública, no la base, los IDs privados o las respuestas esperadas.

**Corrección del simulador.** Al detectar repeticiones, desvíos y borradores con rol de vendedor se pasó a un controlador backend: dos intentos por objetivo, terminación acotada y respaldo trazable. Lab 3 terminó sus nueve controladores, pero solo cuatro casos resolvieron todos sus objetivos percibidos. Terminar no equivale a aprobar.

**Etapa actual: guiones para ahorrar y repetir.** No se redacta manualmente cada conversación por WhatsApp. Una batería define mensajes/objetivos; el controlador lee solo opciones públicas del agente para elegir horario y confirmar. El modelo de ventas sigue siendo real en la corrida del servidor; se sustituyen el transporte y el comprador, no el core.

```mermaid
flowchart TD
    D["Datos y guiones versionados"] --> E["Ejecutar core aislado con modelo publicado"]
    E --> T["Checks, trazas y consumo"]
    T --> R["Revisión y corrección acotada"]
    R --> P["Regresión local con paquetes grabados"]
    P --> E
```

| Conjunto | Para qué se diseñó | Resultado esperado, no necesariamente una cita |
|---|---|---|
| Agenda puntual | Asignación, slots, selección y confirmación | Crear una sola cita tras aceptar el resumen, o explicar ausencia de horarios. |
| Comercial | Contado, inicial, presupuesto inferior, pago/reserva | Informar con hechos publicados, sin cobrar ni prometer crédito. |
| Cierres/retoma | Rechazo, humano, despedida y pregunta posterior | Mantener ayuda disponible y cerrar sin presión. |
| Compacta | Ocho perfiles × A/B = 16 escenarios | Cruzar información, materiales, disponibilidad y decisiones. |
| Selección de tres | PDF/visita, cambio/fotos/rechazo y visita sin segmento | Aislar el bloqueo y repetir barato antes de ampliar. |

**Qué se evalúa:** evidencia, sujeto, preferencias persistidas, recursos entregados, resultado en base, consentimiento, no duplicación y claridad pública. Una cita declarada sin registro no cuenta. Las pruebas locales con HTTP simulado previenen regresiones, pero no miden al modelo real. Esta distinción coincide con evaluación de comportamiento, trazas y estado final [R4–R6]. [Guiones](03-casos-de-prueba/casos-guionados.json) · [Primeros perfiles LLM](02-datos-de-prueba/leads/perfiles-iniciales-adaptativos.json).

## 5. Qué se modifica al afinar

**Afinar aquí significa cambiar instrucciones y código versionados; los pesos del modelo se conservan.** Se localiza un fallo observado, se modifica su causa y se repite la misma conversación más variantes. No se considera mejora únicamente que el texto suene más amable.

| Pieza modificada | Problema observado | Qué se actualizó y cómo | Beneficio buscado |
|---|---|---|---|
| Prompt y esquema de salida | El proveedor rechazaba el formato JSON; después hubo interpretaciones incorrectas. | Se corrigió el esquema aceptado por el proveedor y se versionaron instrucciones con ejemplos de contado, selección, materiales y visita. Se exige citar el mensaje actual como evidencia. | Obtener respuestas procesables y distinguir información, preferencias y consentimiento. |
| Validación semántica | Pedir fotos se interpretaba como pedir una visita; una selección, como comparación. | Se añadieron comprobaciones que contrastan la acción con su cita y rechazan visitas sin petición explícita, acciones incompatibles y evidencia ajena al turno. La reparación recibe la regla concreta incumplida. | Evitar acciones no pedidas y corregir errores sin ocultarlos. |
| Referencias y planificación | Se confundía el nombre de una propiedad con un material o se mostraba un catálogo demasiado amplio. | El backend resuelve nombres solo dentro del project. En Repair 6 vincula una elección explícita única con «sus fotos» en el mismo mensaje, conserva la confianza y elimina la visita inventada; ambigüedades y restricciones siguen bloqueando la acción. | Responder y compartir el recurso de la propiedad elegida. |
| Estado y persistencia | Se perdían presupuesto y preferencia de contado tras un rollback. | Se ajustó la conservación y recuperación de declaraciones verificadas al restaurar el estado de la conversación. Los tests comprueban que sobrevivan errores y no se vuelvan a preguntar datos conocidos. | Recordar lo ya dicho y mantener continuidad. |
| Composición de respuesta | Bloques de evidencia en orden inválido provocaban rechazo y reintentos; Repair 6 también agotó tiempo al confirmar. | Se ajustaron las reglas de selección y orden de bloques completos autorizados. El LLM elige variantes de esa evidencia; el backend valida enlaces y hechos. En Repair 7 un comprobante de cita ya registrada, completo y sin otra decisión se presenta directamente, sin otra llamada al modelo. | Dar respuestas claras sin inventar condiciones ni perder confirmaciones reales. |
| Controlador del lead sintético | El comprador LLM repetía objetivos o respondía como vendedor. | Se limitaron intentos por objetivo y se añadieron condiciones de terminación; después se adoptaron guiones A/B con elección de horarios basada en opciones públicas del agente. | Repetir pruebas válidas con menos consumo, sin escribir manualmente cada diálogo por WhatsApp. |
| Evaluador y regresiones | Se marcaba como fallo una respuesta correcta por no llevar metadata de catálogo. | En Repair 6 el check acepta catálogo acotado o detalle con referencia resuelta a la propiedad esperada. Rechaza referencias erróneas, respuestas vagas o varias propiedades. Se conservaron paquetes reales y variantes negativas como pruebas repetibles. | Medir el comportamiento correcto sin borrar fallos históricos ni relajar el ámbito. |

**Ejemplo de esta entrega.** “Actually I prefer Cedar Loft instead. Please send its photos.” se vincula a la elección explícita del mismo mensaje cuando es única y del ámbito permitido. Se elimina una visita no solicitada, sin elevar la confianza del modelo. Una negación, hipótesis, tercero, varios candidatos o una restricción siguen bloqueando esa recuperación.

**Qué no se cambió para esta comparación:** modelo de ventas, configuración publicada 8, compañía y selección de tres casos. La corrección local se valida con paquetes reales grabados y con negativos; Repair 6 confirmó el cambio y la galería, aunque el conjunto completo sigue con un caso fallido. Los tests de infraestructura y transporte son otra cobertura, no sustituyen calidad conversacional.

[Normalización](../../backend/app/modules/sales_agent/interpretation_consistency.py) · [Planner](../../backend/app/modules/sales_agent/turn_planner.py) · [Compositor](../../backend/app/modules/sales_agent/commercial_composer.py) · [Regresiones nuevas](../../backend/tests/test_sales_current_choice_materials.py).

## 6. Historia y evolución medida

**Qué se conserva.** Desde la primera preparación de fixtures hasta Repair 6 se guardan avances y retrocesos. No hay un ZIP de ejecución “Lab 1” disponible; preparar sin inferencia no es una medición. Los números siguientes son del servidor; no se incluyen tests locales como conversaciones LLM.

| Corrida | Casos aprobados / ejecutados | Visitas / esperadas | Costo total de la corrida (USD) | Acumulado registrado (USD) |
|---|---|---|---:|---:|
| synthetic-lab-2 | 1/9 | No evaluadas | 0.15620250 | 0.15620250 |
| synthetic-lab-3 | 4/9 | No evaluadas | 0.07491450* | 0.23111700 |
| booking-point-1 | 0/6 | 0/3 | 0.08159205 | 0.31270905 |
| booking-point-2 | 0/6 | 3/3 | 0.04804425 | 0.36075330 |
| booking-point-3 | 2/6 | 3/3 | 0.05101845 | 0.41177175 |
| booking-point-4 | 0/6 | 3/3 | 0.06180480 | 0.47357655 |
| booking-point-5 | 2/6 | 3/3 | 0.04668780 | 0.52026435 |
| booking-point-6 | 3/6 | 3/3 | 0.05161695 | 0.57188130 |
| commercial-point-1 | 7/8 | 0/0 | 0.04402260 | 0.61590390 |
| commercial-point-2 | 8/8 | 0/0 | 0.04607130 | 0.66197520 |
| closing-point-1 | 8/8 | 0/0 | 0.02099955 | 0.68297475 |
| compact-battery-1 | 2/16 | 3/8 | 0.15877665 | 0.84175140 |
| compact-repair-1 | 0/8 | 3/4 | 0.12409320 | 0.96584460 |
| compact-repair-2 | 1/8 | 0/4 | 0.08193825 | 1.04778285 |
| compact-repair-3 | 1/3 | 0/2 | 0.05925180 | 1.10703465 |
| compact-repair-4 | 2/3 | 2/2 | 0.04808190* | 1.15511655 |
| compact-repair-5 | 2/3 | 2/2 | 0.04584570 | 1.20096225 |
| compact-repair-6 | 2/3 | 2/2 | 0.04528275* | 1.24624500 |
| **TOTAL HISTÓRICO · 18 corridas** | **45/122 ejecuciones** | **No sumar como conversión** | **1.24624500*** | **1.24624500*** |

\* Suma de costos informados, **parcial**, porque faltan importes de cuatro llamadas. Cada fila contiene el total de esa corrida, no un precio por conversación. El acumulado ya incluye las anteriores: **no se suman entre sí los acumulados**. Se usan ocho decimales y punto decimal para poder comprobar las sumas. `0/0` en comercial/cierres significa que no se esperaba agendar. En agenda hubo checks bloqueados incluso después de obtener tres citas; las definiciones del evaluador también evolucionaron.

**Mejoras observadas:** Lab 2→3 subió de **1/9 a 4/9**, con cambio del simulador; comercial 1→2, de **7/8 a 8/8**; la selección reciente, de **1/3 a 2/3** y de **0/2 a 2/2 visitas**. Cierres aprobó **8/8**. Se reconoce también la regresión de tres a cero visitas entre Repair 1 y 2. No se extrapola una tasa de conversión de clientes reales.

![Historia global y cobertura](05-resultados-y-mejoras/figuras/panorama-global.png)

**Lectura correcta:** las 122 ejecuciones incluyen repeticiones; hay 47 IDs por suite. La subida acumulada mide cobertura y trabajo evaluado, no una curva única de calidad. Las 45 aprobaciones históricas pertenecen a sus controles originales: no se interpreta 45/122 como calidad actual. Para observar la mejora de los mismos casos se reconstruyó su subconjunto en las baterías anteriores, conservando los checks originales.

![Los mismos tres IDs desde la batería inicial](05-resultados-y-mejoras/figuras/casos-comunes-desde-la-bateria.png)

[Datos retrospectivos](05-resultados-y-mejoras/seguimiento-casos-comunes.json) · [18 corridas con commit/modelo/denominadores](05-resultados-y-mejoras/corridas.json). Esta reconstrucción no es una nueva ejecución ni una reevaluación uniforme de versiones pasadas.

## 7. Conversaciones para repetir

**Evidencia, no respuestas ideales.** Son fragmentos de conversaciones ejecutadas. Para probar en un project real se sustituyen nombres y condiciones por sus datos aprobados; se elige un horario vigente, no una fecha copiada de noviembre. Puede variar la redacción: se verifica intención, hechos y resultado.

| Caso y fuente | Qué dijo el lead | Qué hizo/responde el agente | Cómo repetirlo |
|---|---|---|---|
| [Información → PDF → visita](04-conversaciones/funcionaron/primera-compra-pdf-y-visita__first-time-a__sales-compact-repair-5__aprobado.json) | I am buying my first home. My budget is 300,000 USD, paying cash. What can you tell me about Cedar Studio? | Respondió Cedar Studio, entregó el PDF y confirmó solo después de elegir y aceptar el resumen. | Declarar preferencias, pedir material, solicitar visita, seleccionar una opción pública y confirmar. |
| [Cambio y fotos (histórico)](04-conversaciones/funcionaron/cambio-de-propiedad-fotos-y-despedida__move-up-b__sales-compact-repair-3__aprobado.json) | Actually I prefer Cedar Loft instead. Please send its photos. | Cedar Loft gallery: [sandbox-material-link] | Elegir otra propiedad y pedir sus fotos. Regresó en Repair 5 y volvió a aprobar en Repair 6; falta comprobar consistencia. |
| [Sin pago/reserva](04-conversaciones/funcionaron/sin-pago-ni-separacion-en-chat__property-reservation__sales-commercial-point-2__aprobado.json) | Can I reserve Bay Residence and pay the deposit here? | Aclaró que pagos y reservas se atienden en persona; siguió ofreciendo ayuda. | Pedir separar/pagar por chat y verificar que no ejecute ni prometa la operación. |
| [Despedida y retoma](04-conversaciones/funcionaron/despedida-y-retoma__farewell-then-reopen__sales-closing-point-1__aprobado.json) | No other questions, thank you. Goodbye. / What financing options do you offer? | Se despidió y después respondió contado/financiación publicada sin inventar frustración. | Cerrar y enviar una nueva consulta. Esto prueba retoma en la misma corrida, no días de inactividad. |

**Secuencia real de visita, Repair 5.**

- Lead: “Please send the brochure PDF for Cedar Studio.” → agente: “Cedar Studio synthetic brochure: [sandbox-material-link]”.
- Lead solicita visita → el backend ofrece horarios de Chicago.
- Lead elige el primero → agente: “Please confirm your visit: Cedar Studio; 2026-11-13 at 09:00 AM … Shall I book this exact visit?” (extracto).
- Lead: “Yes” → agente: “Your visit is confirmed … What else would you like to know before your visit?” (extracto).

**Avance y bloqueo actual.** Repair 6 entregó la galería de Cedar Loft, respetó el rechazo de visita y cerró amablemente. El caso `move_up_B` pasó de FAIL a PASS. El conjunto permanece en 2/3 porque `first_time_A`, antes aprobado, reutilizó preguntas históricas como si fueran actuales; el validador las rechazó y el reintento agotó su tiempo. El lead tuvo que repetir su solicitud de visita. Al confirmar, otro timeout activó el texto seguro del backend; la cita sí quedó registrada. No es un fallo de entrega WhatsApp ni un nuevo rechazo HTTP 400 demostrado.

**Antecedente conservado.** En Repair 5 el cambio a Cedar Loft con fotos terminó en “Which property option do you mean?” y no entregó galería. Además, el primer check de alcance era un falso positivo: sí respondió solo Cedar Studio con `property_details`. Se mantienen el FAIL original y la revisión separada; no son cuatro causas independientes por aparecer cuatro checks fallidos.

[122 diálogos completos](04-conversaciones/) · [Índice JSON](04-conversaciones/indice.json) · [Revisiones humanas](04-conversaciones/revisiones-humanas.json) · [Diagnóstico Repair 5](05-resultados-y-mejoras/sales-compact-repair-5/diagnostico.json). Un PASS histórico puede contener una limitación no detectada por los checks de entonces.

### Flujos con éxito observado y cómo probarlos con leads reales

**Estos flujos tienen evidencia sintética ejecutada en el servidor y son candidatos a validación real. «Éxito observado» no garantiza que cualquier nueva conversación resulte igual:** pueden variar interpretación, latencia, información aprobada, recursos, vendedores y disponibilidad. Primera compra sigue con el fallo de Repair 6; no se declara resuelto en producción por una prueba local.

| Flujo con evidencia | Prueba sugerida con un lead real | Condiciones para obtener un resultado equivalente |
|---|---|---|
| [Información, PDF y visita · Repair 5](04-conversaciones/funcionaron/primera-compra-pdf-y-visita__first-time-a__sales-compact-repair-5__aprobado.json) | Dar presupuesto y forma de pago; consultar una propiedad, pedir su PDF y solicitar visita. | Propiedad y PDF aprobados, vendedor elegible con slots y confirmación explícita. Es un éxito histórico: Repair 6 registró la visita pero tuvo fallos intermedios. |
| [Cambio de propiedad y fotos · Repair 6](04-conversaciones/funcionaron/cambio-de-propiedad-fotos-y-despedida__move-up-b__sales-compact-repair-6__aprobado.json) | Consultar una propiedad; cambiar a otra por su nombre y pedir «sus fotos»; rechazar visita por ahora. | Ambas propiedades pertenecen al project; la segunda tiene galería vigente y acceso autorizado a leads. |
| [Visita sin segmento · Repair 6](04-conversaciones/funcionaron/visita-sin-segmento__unknown-a__sales-compact-repair-6__aprobado.json) | Preguntar por una propiedad sin declarar motivación; solicitar visita, elegir horario y confirmar. | El agente no debe inventar un segmento. Vendedor activo, asignación válida y horario disponible. |
| [Presupuesto y alternativa accesible](04-conversaciones/funcionaron/affordable-alternative__affordable-alternative__sales-commercial-point-2__aprobado.json) | Indicar un presupuesto inferior y preguntar qué alternativa existe. | Precios, moneda y opción accesible publicados en el ámbito autorizado. No prometer financiación no aprobada. |
| [Pago o separación fuera del chat](04-conversaciones/funcionaron/sin-pago-ni-separacion-en-chat__property-reservation__sales-commercial-point-2__aprobado.json) | Preguntar si puede separar la propiedad o pagar aquí. | Debe informar el límite, seguir ayudando y proponer visita cuando proceda; no cobrar ni reservar. |
| [Despedida y nueva consulta](04-conversaciones/funcionaron/despedida-y-retoma__farewell-then-reopen__sales-closing-point-1__aprobado.json) | Despedirse y luego preguntar por financiación. | Responder la nueva pregunta con lo publicado, conservar preferencias y no inventar emociones. Se probó dentro de la misma corrida, no tras días de inactividad. |

**Calidad de la información real.** El afinamiento usa datos ficticios pero coherentes. Para trasladar esa calidad, la company, el project y sus propiedades deben tener información aprobada con sentido: descripción, campos estructurados, inventario, precios, PDF y galería deben referirse a la misma oferta y versión. Si la descripción dice «tres dormitorios» y la ficha «dos», o el PDF contradice el precio publicado, hay un problema de datos que el agente no puede resolver de manera fiable eligiendo una versión por intuición.

Antes de la prueba real, el responsable de la company debe revisar esas contradicciones, actualizar los materiales y aprobar los datos. Distinguir información desconocida de cero/unidad agotada; verificar moneda, área/unidad de medida y formas de pago; comprobar recursos públicos y asignaciones/horarios de ventas. **Es una condición de preparación, no un nuevo control automático implementado en esta entrega.** El agente debe ceñirse al conocimiento autorizado y reconocer incertidumbres; afinar su conversación no corrige por sí solo datos contradictorios.

Para comprobar el traslado al canal real se registra un lead de prueba en la company/project correctos y se recorre uno de estos guiones con datos reales vigentes. Se revisan respuesta, recurso y cita registrada, no solo similitud textual. WhatsApp/SMS requieren además su configuración y entrega efectiva por el proveedor; el laboratorio no certifica esa última parte.

## 8. Consumo real y saldo de OpenRouter

**Total general registrado de las 18 corridas: USD 1.24624500** (aproximadamente **USD 1.25**). Son 943 llamadas, 10.263.728 tokens de entrada y 149.095 de salida. Hay costo informado para 939/943 llamadas: **es una suma parcial**, no el saldo consultado ni una factura completa. No incluye desarrollo, revisión humana, hosting o mensajería real.

| Etapa | Diálogos | Llamadas | Tokens entrada / salida | Costo total registrado de la etapa (USD) |
|---|---:|---:|---:|---:|
| Lead LLM inicial | 18 | 250 | 2,009,248 / 28,579 | 0.23111700* |
| Agenda | 36 | 244 | 2,953,110 / 42,111 | 0.34076430 |
| Comercial | 16 | 69 | 770,886 / 8,539 | 0.09009390 |
| Cierres/retoma | 8 | 15 | 173,013 / 2,114 | 0.02099955 |
| Baterías/repairs | 44 | 365 | 4,357,471 / 67,752 | 0.56327025* |
| **TOTAL GENERAL REGISTRADO** | **122** | **943** | **10,263,728 / 149,095** | **1.24624500*** |

\* Etapa con costos faltantes. Esta tabla agrupa las mismas corridas del bloque 6: **es el mismo gasto, no un gasto adicional**. Repair 6 aportó USD 0.04528275 informados (28/30 llamadas), no un total final confirmado de USD 0.04528275. No se atribuye un costo por caso cuando el reporte solo lo agrega por corrida.

![Consumo por corrida y acumulado](05-resultados-y-mejoras/figuras/consumo-global.png)

**Por qué cambió.** Acotar el lead LLM redujo sus mensajes de 51 a 26 y las llamadas conjuntas de 159 a 91. Pasar a guiones eliminó otro modelo, no el de ventas. En los mismos tres casos recientes las llamadas fueron 36→31→29 y los costos USD 0,0592518→0,0480819*→0,0458457. El intermedio es parcial: no se afirma ahorro total exacto respecto de él.

**Qué consume una corrida.** El turno puede incluir interpretación, composición y reparación. Más turnos reenvían más contexto; más casos y repeticiones aumentan llamadas. Por eso al ampliar diálogos subirá el consumo de OpenRouter, aunque se mantenga el modelo barato y los leads guionados.

Las gráficas se generan con NumPy y Matplotlib, sin suavizado ni valores inventados. Los futuros presupuestos del bloque final **no se suman** a los consumos reales. [CSV](05-resultados-y-mejoras/metricas.csv) · [Costos/tokens por corrida](05-resultados-y-mejoras/corridas.json) · [Scripts y figuras](05-resultados-y-mejoras/figuras/).

## 9. Referencias y fundamento

**Base del proyecto:** reglas comerciales acordadas, conocimiento aprobado del project y backend con autoridad sobre acciones. Las referencias siguientes explican decisiones de arquitectura/evaluación; no prueban resultados de Black Penguin ni implican que se haya usado su software o citado estos trabajos desde la primera implementación.

| Referencia primaria | Qué respalda | Qué no permite concluir |
|---|---|---|
| R1. Anthropic, [Building effective agents](https://www.anthropic.com/research/building-effective-agents), 2024 | Orquestación por código y patrones simples/componibles. | Que usemos Claude o su implementación. |
| R2. OpenRouter, [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs) | Contrato JSON Schema para analizar salidas. | Que un JSON válido implique intención correcta. |
| R3. Pydantic, [Models](https://docs.pydantic.dev/latest/concepts/models/) | Validación de datos; el repo fija Pydantic 2.13.4. | Que eso mida calidad comercial. |
| R4. Yao et al., [τ-bench](https://arxiv.org/abs/2406.12045), 2024 | Diálogos con herramientas, estado final y consistencia entre intentos. | Que usemos su benchmark o que sus costos sean tarifas actuales. |
| R5. Ribeiro et al., [CheckList](https://aclanthology.org/2020.acl-main.442/), ACL 2020 | Casos de comportamiento, variaciones y detección de fallos. | Que las variantes equivalgan a entrenar pesos o usemos esa librería. |
| R6. Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents), 2026 | Separar tarea, intento, checks, traza y resultado; calibrar con revisión. | Que una corrida favorable garantice estabilidad. |

**Uso responsable de las referencias.** Informan el enfoque; las cifras y correcciones se sustentan en nuestros reportes y código. Las longitudes futuras son límites de experimento, no un promedio científico de conversaciones reales. No se afirma una inversión media de mercado sin evidencia comparable.

[Referencias verificadas el 11/11/2026 en JSON](referencias.json) · [Coordinador real](../../backend/app/modules/sales_agent/active_service.py) · [Batería](../../backend/tools/sales_ai/compact_battery.py).

## 10. Trabajo actual

**Actual — Repair 6 ejecutado en el servidor.** Commit `a5c7b6d`, modelo `openai/gpt-4o-mini`, configuración publicada 8. Resultado original **FAIL: 2/3 casos aprobados; 2/2 visitas registradas**. La corrección de elección + fotos funcionó; la fiabilidad ante salidas inválidas y demoras aún requiere trabajo.

| Caso | Resultado observado | Estado |
|---|---|---|
| Primera compra (`first_time_A`) | PDF entregado y visita registrada; petición de visita repetida tras rechazo de evidencia histórica y timeout. Otro timeout de composición al confirmar. | FAIL, dos checks fallidos. |
| Cambio de propiedad (`move_up_B`) | Cambió a Cedar Loft, entregó su galería y respetó rechazo/despedida. | PASS. |
| Sin segmento (`unknown_A`) | Informó Ridge Townhome y registró la visita con confirmación. | PASS. |
| **TOTAL DE REPAIR 6** | **14 turnos, 30 llamadas; USD 0.04528275 registrados de 28/30 llamadas.** | **2/3 aprobados; costo parcial.** |

**Diagnóstico.** En primera compra, turno 3, el intento inicial incluyó como solicitudes actuales dos citas de mensajes anteriores: el validador marcó `evidence_mismatch`. La reparación terminó en `TimeoutError`. El respaldo ofreció contacto con ventas en vez de avanzar con la visita. En el turno 6 el compositor agotó su ventana de unos ocho segundos; el backend conservó la confirmación real, pero el check de composición falló. No se puede distinguir latencia de red/proveedor o presupuesto de tiempo insuficiente con esta traza solamente.

**Corrección actual — Repair 7, pendiente de ejecución publicada.** El compilador omite solo solicitudes informativas afirmativas que no pertenecen al mensaje actual y cuya cita sí aparece en mensajes anteriores de ese mismo lead/conversación, cuando existe una petición actual de visita validable. Mantiene exclusiones, alternativas, restricciones, solicitudes desconocidas y confianza; no borra preferencias guardadas ni concede consentimiento. El planner conserva la petición actual de visita. Para una cita registrada cuya única salida es el comprobante completo del backend, se evita la inferencia de composición; los turnos mixtos siguen usando el LLM. La traza distingue `backend_rendered` de `accepted` y de un respaldo por error. No se aumentaron timeouts ni se añadieron reintentos ilimitados.

La reproducción local usa los paquetes grabados de Repair 6 y prueba casos negativos; no equivale a un nuevo éxito con el modelo real. Después de desplegar se repiten los mismos tres casos antes de ampliar. **Costo total estimado de esa repetición: USD 0.04–0.09**, con reserva orientativa total USD 0.08–0.17; no se suma al gasto ejecutado ni se promete ahorro de costo final.

Las 20 pruebas específicas y 3.023 pruebas locales aprobadas (siete omitidas) de Repair 6 fueron cobertura de código, no certificación del modelo. Repair 7 completó la regresión: **3.041 pruebas aprobadas y siete omitidas**, con 129 módulos cubiertos una vez. La versión final de las pruebas específicas aprobó **22/22** (18 ya incluidas en esa regresión; cuatro negativos se añadieron y verificaron después). Aceptación técnica: **63 PASS, 0 FAIL, 1 NOT_RUN** para calidad live. Estas pruebas usan inferencia simulada y no consumieron saldo de OpenRouter. El archivo recibido acredita ejecución del core aislado en servidor; hubo **cero escrituras en la base productiva y cero contactos con leads reales**. Tampoco acredita entrega por operador, Calendar externo o concurrencia real.

[Validación local Repair 7](05-resultados-y-mejoras/repair7-validacion-local.json) · [Resultado JSON](05-resultados-y-mejoras/sales-compact-repair-6/resultado.json) · [Diagnóstico y checks](05-resultados-y-mejoras/sales-compact-repair-6/diagnostico.json) · [Conversaciones completas](04-conversaciones/).

## 11. Trabajo futuro

**Más casos y conversaciones más largas, no nuevas funciones de canal.** Se avanza por etapas, corrigiendo y repitiendo antes de ampliar. Se incluyen compradores que rechazan o abandonan: no toda conversación correcta termina con cita [R4–R6].

| Etapa propuesta | Conversaciones × turnos de lead | Beneficio / criterio de avance | Costo total estimado de la etapa (USD) | Reserva total 2× (USD) |
|---|---|---|---|---|
| Batería base | 16 × 6–8 | Cubrir los 16 escenarios sin checks obligatorios fallidos. | 0.34–0.45 | 0.68–0.90 |
| Variantes | 32 × 8–12 | Dos variantes por escenario: negación, pronombres y consultas múltiples. | 0.90–1.35 | 1.81–2.71 |
| Diálogos largos | 16 × 12–16 | Interrumpir/retomar temas y cambiar datos sin olvidar preferencias ni entrar en bucles. | 0.68–0.90 | 1.35–1.81 |
| Consistencia | 48 × 8–12 | 16 escenarios repetidos tres veces; revelar inestabilidad, no solo un PASS. | 1.35–2.03 | 2.71–4.06 |
| **TOTAL DE LAS CUATRO ETAPAS** | **112 conversaciones** | **Una ejecución de cada etapa; solo planificación.** | **3.27–4.73** | **6.55–9.48** |

**Totales futuros:** se sumaron los importes mostrados por fila; la reserva es una alternativa de presupuesto y **no se añade al estimado base**. Tampoco se suman estos USD al histórico ya ejecutado.

**Cálculo y límites.** Base Repair 5: 13 turnos, 29 llamadas, 331.131 tokens y USD 0,0458457 completos: ≈2,23 llamadas y USD 0,00353 por turno. Se extrapola linealmente manteniendo guiones, sin juez y con el mismo modelo. La reserva 2× es planificación, no intervalo estadístico ni garantía: historia más larga, precios/proveedor o reparaciones pueden superarla. Límites de llamadas no son límites en dólares. [Tokens, llamadas y supuestos por etapa](05-resultados-y-mejoras/propuesta-ampliacion.json).

**Cuánto invertir.** No se encontró un promedio comparable de inversión total para este producto. Como escala histórica, τ-bench reportó USD 0,38 de GPT-4o agente + USD 0,23 de GPT-4 usuario por tarea en 2024: escalar ese ejemplo a 100–500 tareas da USD 61–305 por repetición, sin trabajo humano ([§5.1](https://arxiv.org/html/2406.12045v1#S5.SS1)). No es un precio actual de OpenRouter ni una norma del sector. Nuestro uso de guiones y `gpt-4o-mini` tiene otra escala. Se propone una bolsa inicial propia de USD 5 para primeras ampliaciones o USD 10 si incluye largos/repeticiones, revisada por bloques; no garantiza estabilización ni cubre horas de ingeniería/revisión.


Antes de ejecutar la ampliación hay que preparar sus guiones y checks: los 32 casos y los diálogos largos no están incorporados todavía como nueva batería. Las tres repeticiones serán corridas separadas. Se actualiza el costo observado después de cada bloque, sin sumar estimaciones al histórico.
