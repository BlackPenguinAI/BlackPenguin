# P2-A — Compilación reutilizable de LangGraph (17 nov. 2026 / 18 nov. UTC)

## Alcance

El coordinador comercial (`sales-coordinator-graph/4.0`) antes construía `StateGraph` y hacía `graph.compile()` en cada llamada a `execute()`; en operación corresponde a cada turno ejecutado por `active_service.py`. El cambio mueve la topología a `_build_compiled_graph()` y la mantiene en una caché **por proceso** protegida por `threading.Lock`, compilada de forma **perezosa** en la primera invocación. Las réplicas API/worker y los procesos separados tienen cada uno su propia compilación. Reiniciar o desplegar crea una nueva caché por proceso.

Los callbacks de interpretación, planificación, observación, composición y auditoría **no se almacenan en la caché**. Cada `execute()` crea un `TurnCallbacks` congelado y lo pasa mediante `context=` a `ainvoke`; cada nodo lo obtiene exclusivamente desde `Runtime[TurnCallbacks]`. La sesión de base de datos solo puede estar referenciada por callbacks del turno actual. No hay checkpointer de LangGraph ni cambios en persistencia empresarial, consentimiento, autorizaciones, calendarios o envíos.

La topología, los nombres y el orden de los nodos, el `recursion_limit=10`, el retorno `version/mode/trace/route/observation_route/reconsiderations/status`, los defaults y la estrategia *fail closed* se mantienen. `VERSION` continúa en `sales-coordinator-graph/4.0` por tratarse de una optimización sin cambio de contrato de grafo.

## Validación local o CI (no consume créditos)

Desde `backend/`, con `langgraph==1.2.11` y dependencias instaladas:

```bash
python -m tools.sales_ai.p2a_compile_selftest
python -m tools.sales_ai.p1_routing_selftest
python -m tools.sales_ai.p1b_routing_selftest
python -m tools.sales_ai.p2a_compile_benchmark --iterations 100
python -m pytest -q tests/test_sales_p1_routing.py tests/test_sales_p1b_routing.py tests/test_sales_p2a_compile.py
```

Comprobar el test de cold-start concurrente (una compilación en 12 hilos) y las 16 ejecuciones async con rutas distintas, fallos aislados y trazas por conversación. El benchmark compara solo el trabajo de construir+compilar con la consulta en caché en el mismo proceso: **no** equivale a latencia de turno ni reducción de tokens o costo LLM. No inferir reducción porcentual productiva de estos números.

## Comandos sugeridos después de desplegar

```bash
docker inspect --format '{{.Name}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}' bp_api_prod bp_worker_prod
curl -fsS --connect-timeout 3 --max-time 15 http://127.0.0.1:8000/api/v1/health/version

docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p2a_compile_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1_routing_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1b_routing_selftest
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p2a_compile_benchmark --iterations 100
```

Solo tras esas pruebas, ejecutar una **única** batería pagada en laboratorio si se requiere equivalencia de modelo:

```bash
batch="bp-p2a-validation-$(date -u +%Y%m%dT%H%M%SZ)"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite closing-point --orchestrator graph-observe \
  --max-calls 80 --max-turns 4 --output "/tmp/$batch/closing"
# La salida solo es válida si el proceso indicó PASS/FAIL y emitió el bundle.
mkdir -p "$HOME/$batch"
docker cp "bp_api_prod:/tmp/$batch/closing/synthetic-sales-results.zip" "$HOME/$batch/closing.zip"
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p1b3_cost_report \
  "/tmp/$batch/closing/synthetic-sales-results.zip" > "$HOME/$batch/metrics.json"
tar -czf "$HOME/$batch.tar.gz" -C "$HOME" "$batch"
echo "$HOME/$batch.tar.gz"
```

**Criterio de avance:** mismas rutas y comprobaciones; ninguna contaminación entre leads; cero fallos de seguridad; calidad de cierre al menos equivalente dentro de la variación histórica, y medición real de CPU/latencia antes de afirmar una mejora. `closing-point` no convierte por sí solo todas las decisiones internas del observador en aserciones de calidad; mantener su revisión separada.

## Seguridad y rollback

- `git apply --reverse` del parche P2-A y redeploy del commit anterior si aparece error de `Runtime.context`, concurrencia, estado o rutas. No cambiar el contrato de interpretación ni reparaciones en este diferencial.
- El `context` de `ainvoke` puede incluir referencias a datos sensibles del turno a través de callbacks; no se registra, serializa, imprime ni añade a `State` y no se configura un checkpointer.
- No compartir sesiones SQLAlchemy entre distintos turnos; la aplicación ya las maneja. No añadir contexto per-turn a un objeto global ni a atributos de nodos.
- El parche no modifica `active_service.py`: conserva sus hooks y el punto de integración actual.
