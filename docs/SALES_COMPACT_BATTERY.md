# Primera batería compacta del agente de ventas

Base: `d5ad9bca17092fcaf99aea25a79c4fa662b26ab3`. Esta entrega añade un instrumento de evaluación; no modifica el modelo publicado, los prompts ni el motor comercial.

## Alcance y ejecución

16 conversaciones independientes: 8 recorridos con visita confirmada como objetivo y 8 variaciones. Cada conversación tiene su propio lead, historial y equipo. No hay un LLM lead ni juez: los mensajes están guionados y el controlador solo selecciona horarios presentes en la respuesta pública. Una visita requiere solicitud, selección de una opción pública y confirmación posterior. Si el agente no avanza, el controlador termina con fallo, sin inventar una reserva.

El agente usa la configuración global Sales publicada en el momento de iniciar la corrida, incluido su modelo de OpenRouter. No se fuerza otro modelo ni se consume presupuesto de un lead/juez. La configuración se copia mediante lectura a una base SQLite temporal con el esquema completo. El coordinador actual, interpretación, composición, perfil, materiales y persistencia de visitas son los reales del repositorio.

1 company sintética, 3 projects aprobados, 6 property types:

| Project | Property type | Precio USD | Inventario confirmado | Materiales |
|---|---|---:|---|---|
| Harbor Gardens | Bay Residence | 780,000 | 3 | Galería y PDF |
| Cedar Heights | Cedar Loft | 325,000 | 5 | Galería |
| Cedar Heights | Cedar Studio | 210,000 | 2 | PDF |
| Sierra Commons | Ridge Townhome | 460,000 | 4 | Ninguno |
| Sierra Commons | Summit Villa | 620,000 | 0 | Galería y PDF |
| Sierra Commons | Valley Apartment | Sin confirmar | Sin confirmar | Ninguno |

Cada lead comienza sin segmento asignado. Siete perfiles declaran su motivación en lenguaje natural; Alex no declara una motivación clasificable. Los segmentos esperados son criterios del evaluador y nunca se inyectan como respuestas al modelo. No se utilizan datos demográficos para asignarlos.

## Matriz de conversaciones

A implica visita confirmada, B no debe crear una visita.

| Perfil | Segmento esperado | Caso A | Caso B |
|---|---|---|---|
| Emma Torres | first_time_buyer | Cedar Studio, cash, PDF, visita | Inicial versus presupuesto total, financiación, PDF, rechaza visita, despedida |
| Daniel Brooks | move_up_buyer | Bay Residence, cash, galería, visita | Cambia de Cedar Studio a Cedar Loft, pide fotos, rechaza visita |
| Sofia Reed | relocation | Bay Residence, ubicación/entrega, vendedor con varios projects, visita | Vendedores sin asignación elegible, explica falta de disponibilidad, cierre |
| Martin Vega | downsizing | Cedar Studio, PDF, vendedor con un project, visita | Ridge sin fotos y consulta por Summit agotado, rechaza visita |
| Lucas Chen | rental_yield_investor | Ridge Townhome, cash, visita | Rentabilidad no publicada y Valley sin precio/inventario confirmado, cierre |
| Valeria Cruz | appreciation_resale_investor | Bay Residence, cash, visita | Presupuesto menor, financiación publicada, intenta reserva/pago en chat, cierre |
| Adrian Park | portfolio_diversification | Compara Cedar Loft/Studio, galería de Loft, elige segundo horario, visita | Comparación, vendedor elegible sin slots, cierre |
| Alex Rivera | Sin segmento | Ridge Townhome, cash, visita | Pide humano, insiste, solicitud persistida una vez, despedida |

El equipo se crea por conversación usando las funciones de asignación del producto: un vendedor candidato, uno asignado a otro project, uno sin projects, uno inactivo y otro que no acepta citas. Todos pertenecen a la company sintética. El candidato tiene acceso a todos, varios, uno o ningún project según el caso. Los casos sin vendedores y sin slots son distintos. Los demás vendedores tienen horarios para comprobar que no se ofrezcan por error.

## Aserciones y trazas

- Perfil leído en una sesión nueva después de cada commit: presupuesto, cash como compra de contado sin financiación y segmento con evidencia de la declaración del propio lead.
- Interpretación y composición aceptadas; ausencia de mensajes técnicos al lead, repeticiones y preguntas de presupuesto ya respondidas.
- Material solicitado: token emitido por el core, resolución interna, permisos y asociación a company/project/lead/property, bytes y hash del PDF o galería. El ZIP incluye copias locales de los materiales.
- Ausencia de fotos, inventario agotado o no confirmado y rentabilidad no publicada: no deben convertirse en datos inventados.
- Visita: vendedor elegible, project, propiedad, horario público seleccionado, zona horaria, dirección y confirmación almacenada. No hay pagos ni reservas de propiedades.
- Cierre sin visita y solicitud humana: cero visitas involuntarias; petición humana conservada; despedida sin volver a preguntar.
- Repetir el último evento no duplica mensajes, materiales ni citas ni consume nuevas llamadas al modelo.

`summary.json` y `report.json` incluyen checks por turno y por conversación, `case_results` con fallos resumidos, estado final, IDs de las visitas privadas y consumo reportado por OpenRouter. `report.md` permite leer el diálogo. `scenario-plan.json` conserva los guiones y las expectativas; `catalog.json` conserva el catálogo. Los checks automáticos no sustituyen la revisión de la naturalidad ni demuestran calidad universal para un segmento.

Un fallo de interpretación, una respuesta incompleta o llegar al límite de turnos hacen fallar el caso. La batería conserva el ZIP aunque el proceso termine con código 2; no convierte esos casos en aprobados para permitir desplegar. Las pruebas de regresión offline comprueban que el evaluador detecte fallos deliberados o presentes en las respuestas construidas sin modelo real; no exigen que el modelo publicado haya aprobado los 16 casos antes de poder desplegar el evaluador.

## Límites y costo

Normalmente 3–6 mensajes del lead por conversación, con un máximo de 8, incluidas aclaraciones. Un turno aquí es un mensaje entrante y la respuesta del agente. Máximo global de 320 llamadas de inferencia, repartidas en 20 por caso en la corrida completa. Una interpretación puede reintentarse y una composición implica otra llamada. El límite es de llamadas, no de dólares. El costo se obtiene de `provider_usage`; si el proveedor omite costos no es un total completo. No se introducen nuevos costos de modelos en GitHub Actions.

No se escriben datos de producción ni se contacta a leads. Las visitas se guardan de verdad en la base descartable; desaparecen al acabar. Google Calendar, entrega WhatsApp/SMS, concurrencia PostgreSQL y round-robin de producción no se validan aquí. Los enlaces emitidos solo existen en esa base temporal: no sirven para abrirlos después contra producción. Se comprueba el resolver y los bytes internos, no el middleware HTTP de acceso público. Para inspeccionar los materiales, usar los archivos locales del ZIP. Una visita aprobada aquí no garantiza entrega por el proveedor ni creación en Google Calendar.

## Comandos después del despliegue

SSH, corrida completa:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 320 --max-turns 8 \
  --output /tmp/sales-compact-battery-1
```

Ejecutar este segundo comando incluso si la evaluación termina con código 2:

```bash
docker cp bp_api_prod:/tmp/sales-compact-battery-1/synthetic-sales-results.zip ~/sales-compact-battery-1.zip
```

PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-battery-1.zip "$env:USERPROFILE\Downloads\sales-compact-battery-1.zip"
```

Adjuntar el ZIP completo para analizar los casos y decidir los siguientes ajustes. No es necesario pegar las trazas en consola.

Preparar catálogo y guiones sin leer la configuración de producción ni llamar al modelo:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery --prepare-only --max-turns 8 \
  --output /tmp/sales-compact-preview-1
```

Repetir solo casos que fallen, conservando una carpeta distinta por corrida:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases relocation_B rental_B --max-calls 40 --max-turns 8 \
  --output /tmp/sales-compact-rerun-1
```

El informe de una selección marca `is_full_battery=false`. Aprobar una selección no equivale a aprobar las 16 conversaciones. Los nombres inválidos o repetidos se rechazan antes de leer credenciales. `--lead-model` y `--judge` no se admiten en esta batería.

## Hallazgos del preflight sin modelo real

Los ensayos con respuestas HTTP simuladas verifican el evaluador y crean las ocho visitas esperadas. No acreditan la calidad del modelo publicado. Se observaron tres puntos que la batería mantiene como fallos visibles, sin modificar el motor en esta entrega:

1. El filtro local identifica `Is Summit Villa available?` como estonio (`et`) y solicita volver a escribir en inglés, aunque la pregunta ya está en inglés. El caso señala tanto el bloqueo de idioma como la consulta de inventario sin respuesta.
2. La respuesta construida al comparar Cedar Loft y Cedar Studio repite una advertencia de precio/disponibilidad, una vez por propiedad. Se registra como repetición en ambos casos de comparación.
3. La interpretación offline de rentabilidad como `other` recibe una pregunta genérica y no una aclaración de que las cifras no están publicadas. El caso exige esa aclaración y no inventar porcentajes. La corrida con el modelo publicado permitirá comprobar su interpretación real.

Las pruebas CI verifican que esos fallos, y un HTTP 400 deliberado, se reflejen en el informe y en un código de salida no exitoso. No convierten el preflight en un resultado de calidad aprobado ni fijan que esos defectos deban permanecer para que una futura mejora pase los tests.

## Validación de esta entrega

- 50 pruebas del evaluador aprobadas con HTTP de modelo simulado, usando sesiones con `autoflush=False` y `True`. Tras revisar las aserciones de URLs y datos desconocidos, se repitieron las 50 y pasaron.
- Regresión completa: 2,771 pruebas aprobadas, 7 omitidas; 122 módulos cubiertos exactamente una vez por los tres shards.
- Aceptación técnica: 63 PASS, 0 FAIL, 1 NOT_RUN (evaluación real posterior al despliegue).
- CLI `--prepare-only`: 16 escenarios, 3 projects, 6 property types, 0 llamadas al modelo.
- Sin modificaciones en prompts, lógica comercial, esquema SQL ni dependencias. El peso medido del nuevo módulo de tests se incorpora al reparto de CI para equilibrar los shards.

Extraer el ZIP diferencial en la raíz del repositorio, conservando las rutas `backend/` y `docs/`.

```bash
git pull && git add . && git commit -m "Add compact scripted sales evaluation across buyer segments and booking availability" && git push
```
