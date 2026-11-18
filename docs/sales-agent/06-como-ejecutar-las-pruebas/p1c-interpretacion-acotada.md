# P1-C — Interpretación 3.0: comparación fuera de las solicitudes independientes

**Base exacta:** commit `a5108ef31deb66856d0bb9ada12d9f259ee9c043` (P2-A). Diferencial exclusivo de código y pruebas; no se cambia el repositorio remoto, el servidor, la configuración publicada ni los datos de leads al preparar el ZIP.

## Causa y cambio

En `closing-point` (25 turnos, 404 PASS) se observaron tres reintentos de interpretación. Los tres tuvieron un mismo antecedente: `What financing options do you offer?` fue interpretada como `topic=comparison` en `requests`. El primer caso falló por varias comparaciones (`Only one comparison per turn is supported`); los otros dos fallaron al faltar una pregunta independiente de financiamiento. Una corrida aislada no prueba causalidad ni una tasa estable.

El contrato interno `sales-understanding/1.0` **no cambia**; sigue siendo el único que habilita el planificador, la autorización, los recibos y los controles de empresa/proyecto. El formato histórico `sales-interpretation-input/2.0` sigue aceptado para reproducciones y pruebas existentes.

El contrato **enviado al proveedor** se convierte en `sales-interpretation-input/3.0`:

- `requests` admite solo información/catalog, detalles y materiales: ya **no** permite `comparison` como categoría principal. Se fusionaron las variantes `InformationRequest` y `CatalogRequest` del esquema público.
- Una comparación real de propiedades/unidades se expresa en **`comparison` a nivel superior**; nulo si no existe. El compilador valida primero la respuesta v3, luego la transforma explícitamente al contrato v2 tipado y finalmente al `Understanding` de siempre. Los IDs y referencias siguen generados exclusivamente por backend.
- Los grupos `alternatives` siguen aceptando las comparaciones dentro de alternativas (OR), utilizando las variantes de información consolidadas; por lo tanto, no se pierde expresividad anterior de OR. Las preguntas independientes sobre financiamiento se conservan en `requests` (AND).
- Se mejora la instrucción de clasificación: `financing options` no equivale a comparación entre viviendas.
- Se conserva una única reparación acotada **sin añadir arreglos heurísticos nuevos**. Se mantiene `schema` estricto con evidencias textuales; ningún paso concede consentimiento, reserva, material o contacto humano.

## Validación offline previa a cualquier prueba pagada

Ejecutar después del despliegue:

```bash
# Verificar mismo commit para API y worker
for c in bp_api_prod bp_worker_prod; do
  docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' "$c"
done

# El proveedor NO es llamado por estos selftests
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1c_interpretation_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1_routing_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1b_routing_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p2a_compile_selftest
```

## Prueba de compatibilidad real del formato OpenRouter

El validador offline no demuestra aceptación del nuevo esquema por el proveedor. Realizar el **probe de una llamada** antes de hacer la batería; el script existente `probe_interpretation` ahora emite y exige v3. El probe elige la única configuración global publicada, sin tener que copiar su UUID o las credenciales. Si hay más de una, proporciona `--configuration-id` explícitamente; no copiar ninguna credencial en comandos o reportes.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.probe_interpretation
```

Si el proveedor rechaza `json_schema` o el probe no devuelve `accepted`, no seguir con la batería y revertir este cambio. El probe lee configuración global, usa un lead sintético y no envía mensajes reales; sí consume una llamada a modelo.

## Batería focalizada y comparador

Solo después de `probe=accepted`:

```bash
batch="bp-p1c-closing-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite closing-point --orchestrator graph-observe \
  --max-calls 80 --max-turns 4 --output "/tmp/$batch"

# Revisa el status PASS antes de copiar y comparar; si falla, no publicar resultados como éxito.
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1c_interpretation_report \
  --reference /app/tools/sales_ai/p1c_reference.json \
  --candidate "/tmp/$batch/synthetic-sales-results.zip" \
  --output "/tmp/$batch/p1c-comparison.json"

mkdir -p ~/bp-p1c-results
docker cp "bp_api_prod:/tmp/$batch/synthetic-sales-results.zip" ~/bp-p1c-results/closing-point.zip
docker cp "bp_api_prod:/tmp/$batch/p1c-comparison.json" ~/bp-p1c-results/p1c-comparison.json
tar -czf ~/bp-p1c-results.tar.gz -C ~ bp-p1c-results
```

**Nota:** El JSON agregado de referencia también se instala en `backend/tools/sales_ai/p1c_reference.json`, dentro del árbol Python del contenedor (`/app/tools/...`). El modelo puede fluctuar, por lo que una sola batería no prueba reducción estable de reintentos o USD.

PowerShell (formato solicitado):

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/bp-p1c-results.tar.gz "$env:USERPROFILE\Downloads\bp-p1c-results.tar.gz"
```

## Criterios de avance

1. `p1c_interpretation_selftest`: todos los tests PASS, incluyendo tres errores históricos, comparación legítima y OR material + financiación.
2. `probe_interpretation`: modelo acepta el esquema estricto v3; no evaluar si no acepta.
3. `closing-point`: los mismos 8 escenarios y 25 turnos, al menos 404 PASS, sin FAIL ni nuevos BLOCKED; comparar resultados y trazas por fase.
4. Verificar que el financiamiento no es `comparison`, que el comprador humano y la negativa a visitar no se pierden, y que no aparecen efectos externos.
5. Los reintentos y costos se reportan, no se declaran mejoras hasta repetir cohortes comparables con el mismo modelo/configuración. La eliminación de reparaciones redundantes queda para la fase siguiente, **no forma parte del parche**.

**Límites:** este ajuste reduce las opciones del modelo para clasificar preguntas independientes, pero no garantiza por sí solo menos tokens o dólares; el esquema global conserva el resto de campos para no perder acciones comerciales legítimas. El comparador no califica empatía, tono, conversión ni calidad integral de respuestas.
