# Sales AI — Grupo D: pasos 7 y 8

Fecha: 8 de noviembre de 2026. Base: `2c6814951188afb75637295f161941260b99f72f`.
Rama: `sales-ai/group-d-reference-planning`. Continúa los grupos A–C.
Siguiente grupo: **E, pasos 9 y 10**, todavía pendiente. Resultados: `group-d-report.json`.

## Paso 7 — Referencias y cambios de interés

`reference_resolution.Resolver` enlaza las expresiones del lead con tipologías y
unidades del catálogo aprobado de su Project. Mantiene el aislamiento de Company,
Project, conversación y lead. No cambia automáticamente de oportunidad/proyecto para
buscar una coincidencia en otro tenant o proyecto; ese traslado requiere el flujo de
enrutamiento correspondiente. Las citas ya reservadas conservan las referencias de C.

| Referencia | Resolución |
|---|---|
| Nombre exacto de tipología | Coincidencia normalizada de mayúsculas, espacios y Unicode contra datos aprobados |
| Código exacto de unidad | Unidad del inventario aprobado; su tipología solo se asocia si coincide inequívocamente |
| “This one”, “that property” | Interés actual válido, con aclaración si falta |
| “The other one” | La otra opción si queda una sola; si quedan varias, pregunta con opciones pertinentes |
| Ordinal sin tipo, como “2” | Oferta actual aceptada por el proveedor; no una lista reordenada de DB ni un horario antiguo |
| Referencia explícita a un horario anterior | Oferta suspendida aún vigente, conservando su mensaje y vencimiento originales |
| Referencia inexistente, revocada o ambigua | Aclaración de esa necesidad, sin silenciar ni pausar el chat |

No se usa similitud difusa para adivinar una unidad. Un nombre o ID ajeno no se convierte
en permiso de lectura. Las referencias ordinales conservan el orden de la oferta enviada
aunque cambie `sort_order`. Las ofertas multipartes solo habilitan selección cuando el
grupo está completo y sus partes fueron aceptadas. Una respuesta manual sustituye las
ofertas anteriores como autoridad de selección. La aceptación del proveedor no se presenta
como confirmación de entrega al teléfono.

Las ofertas anteriores pueden quedar `suspended`: sirven para retomar un tema de forma
explícita, pero un número de propiedad no resucita un slot suspendido. No se renueva un
vencimiento al interrumpir ni al recuperar contexto. Si se pide de nuevo disponibilidad,
se consulta otra vez por el mecanismo existente; no se presenta un horario vencido como
recién verificado. Una selección ordinal de propiedad sigue sin ser consentimiento de cita.

El contrato técnico nuevo es `sales-understanding-prompt/2.2`. Añade IDs locales de
referencias, enlaces `reference_id` por solicitud/restricción, tipo `unit` y selección
explícita `selected_reference_id`. Son identificadores del análisis, no IDs de DB elegidos
por el modelo. Sus enlaces se validan antes de usar herramientas. Los registros históricos
que omiten estos campos siguen cargando con sus valores predeterminados.

Una comparación de A y B enlaza cada consulta por separado y no selecciona arbitrariamente
la última propiedad mencionada. Una elección explícita actualiza el interés y limpia la
unidad anterior si corresponde. Presupuesto, restricciones y reservas se conservan. Los
materiales se buscan para la tipología enlazada a **cada tarea**, no siempre para la última
selección global. No se atribuye cobertura específica de unidad a un PDF genérico de su
tipología: se informa la cobertura desconocida y se ofrece el material relacionado.

Cuando una pregunta del agente pide aclarar para qué propiedad eran los planos, una
respuesta posterior como “Loft” puede reanudar esa petición original. La vinculación exige
la pregunta realmente enviada, la tarea pendiente identificada y la selección válida del
turno actual. La traza conserva `resumed_requests`. No se infiere una reserva o cancelación
de esa respuesta de propiedad. Las negativas con referencia desconocida retienen el tema
afectado; la aclaración concreta su propiedad, sin borrar la negativa ni restricciones de Company.

## Paso 8 — Planificación a partir de resultados

`turn_planner` interpreta las necesidades ya estructuradas; no clasifica intención
comercial mediante reglas de palabras. El flujo nuevo se aplica solo a la cohorte de B:

1. Valida evidencia del mensaje, alcance e idempotencia.
2. Resuelve referencias y separa solicitudes, exclusiones y alternativas.
3. Conserva cada necesidad en tareas enlazadas o en una deferral explícita por capacidad.
4. Ejecuta lecturas autorizadas dentro de sus presupuestos.
5. Devuelve resultados tipados a la decisión: completa lo verificado, mantiene lo faltante,
   desbloquea dependencias y elige una alternativa con archivo/enlace aprobado configurado.
6. Reconsidera lo pendiente hasta acabar, agotar un límite o no obtener información nueva.
7. Devuelve resultados y continuación al compositor/coordinador. Las escrituras conservan
   su autorización específica y sus comprobaciones transaccionales de backend.

Una referencia ambigua de planos no bloquea una consulta independiente de financiación.
Las conjunciones AND retienen todas las necesidades y los grupos OR eligen una alternativa
apta; encontrar metadatos o fotos posiblemente incluidas en un PDF no equivale a haber
enviado un archivo. Si la alternativa directa sí está disponible, se prefiere a ofrecer
una cobertura incierta de la otra. Una consulta de citas usa el lector de C y no inicia
agendamiento ni repite esa lectura fuera del presupuesto de planificación.

Las exclusiones por propiedad/unidad se guardan en `property_constraints`, separadas de
las negativas globales. Se aplican al destino de cada herramienta y no se levantan al
cambiar de interés. Se preserva además la protección defensiva de “no visit yet” aunque
el modelo omita esa restricción en un mensaje mixto. Las restricciones aprobadas de Company
y Project siguen acumulándose en las herramientas; ninguna decisión del plan las dispensa.

### Límites y continuación

| Presupuesto | Predeterminado | Máximo validado |
|---|---:|---:|
| Lecturas/pasos `max_steps` | 8 | 30 |
| Rondas `max_rounds` | 3 | 6 |
| Tiempo de planificación `max_seconds` | 5 s | 30 s |
| Unidades internas de lectura `max_read_units` | 12 | 60 |

Catalog/inventory/materials/appointment consumen dos unidades internas; las demás lecturas,
una. Estas unidades limitan trabajo de herramientas; **no son una estimación de dólares
ni tokens de OpenRouter**. El replanificador es determinista y no hace llamadas LLM
adicionales. La interpretación inicial conserva el máximo existente de una inferencia
y una reparación acotada, con su timeout. Ese timeout de interpretación es separado
del presupuesto del plan. El compositor comercial LLM posterior pertenece a E.

No se repite una lectura sin nueva información dentro del mismo turno. En turnos
posteriores, un cambio de información/política aprobada puede reconsiderar una lectura
bloqueada; un saludo no dispara tareas comerciales antiguas. Un pedido nuevo explícito
puede volver a intentar la necesidad sin repetir un resultado del mismo evento. Las
tareas materiales o de escritura antiguas nunca ejecutan automáticamente sus efectos.

Al alcanzar un límite se indica qué temas quedan y se pregunta cuál atender después.
No se pausa ni se toma el límite como autorización para reservar o enviar archivos.
Las tareas terminales se retiran del conjunto de trabajo y su evidencia permanece en
eventos inmutables; se conservan los destinos de dependencias aún necesarias. Si cien
tareas abiertas impiden aceptar otra en el estado, la solicitud nueva se registra completa
en `deferred_requests` del evento y se pide prioridad, sin marcarla como resuelta ni
ejecutarla silenciosamente. No es una cola que pueda ejecutar escrituras sin un nuevo turno.

La traza `planning` incluye referencias, cobertura de cada solicitud, lecturas y rondas,
hashes de resultados/contexto, restricciones, tareas retiradas, deferrals y causa de parada.
Los reintentos reutilizan el resultado persistido del mismo evento; cambiar entrada o
presupuestos con la misma clave provoca conflicto. Los destinos de herramientas deben
coincidir con la vinculación validada, no con otro ID elegido después.

## Compatibilidad, pruebas y límites pendientes

Se conserva el control de activación de B, apagado por defecto y con allowlist explícita
de Project. No se publican prompts ni se cambia el modelo configurado. D no añade
migraciones SQL; sí necesita que las migraciones de C ya estén aplicadas antes de arrancar
el código acumulado. No se cambió frontend ni se desplegó en producción.

```bash
cd backend
BP_PYTHON=python bash tools/sales_ai/offline.sh group-d
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-a-replay.json
```

Las pruebas nuevas cubren nombres y ordinales, ofertas incompletas/vencidas, comparaciones,
selección de unidades, material por propiedad, negativas acotadas, aclaración y retorno a
una petición anterior, AND/OR, dependencias, datos nuevos, errores, presupuestos, idempotencia
y compactación/capacidad. Se prueba por el coordinador real la interrupción de agenda para
pedir planos, su retorno y la reserva solo después de confirmar el horario. También se
usan los seis proyectos exportados por SMS/WhatsApp, sin corregir precios ni inventar
materiales reales. Los modelos y proveedores se simulan: no es aceptación comercial con
el modelo real ni aceptación end to end de T01–T26.
La existencia física y el contenido de los archivos no se acreditan por esos metadatos;
su validación final corresponde a E.

La redacción comercial natural y la validación final de materiales corresponden a E.
El ciclo completo de reserva, cambios/cancelación y reactivación conserva sus grupos
posteriores. El simulador anterior no representa la nueva cohorte activa. Docker no está
disponible aquí: se verifica una copia física de la disposición de Actions, sin afirmar
haber construido ni ejecutado la imagen real o realizado un despliegue remoto.
