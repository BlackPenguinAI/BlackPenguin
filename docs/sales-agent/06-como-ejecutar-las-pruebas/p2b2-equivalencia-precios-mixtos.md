# P2-B.2: equivalencia funcional del normalizador de precio + contacto humano

## Objetivo

Evaluar si `mixed_human_pricing.normalize_misread_price_comparison` puede retirarse después del contrato de interpretación del proveedor `sales-interpretation-input/3.0`, **sin desactivarlo en producción**.

La función original transforma una comparación de **una sola propiedad y criterio precio** emitida erróneamente por el modelo en una solicitud de `pricing`, únicamente cuando el mensaje actual contiene una pregunta literal de precio precedida por una solicitud de contacto humano y el nombre coincide con un único inmueble del catálogo autorizado.

## Alcance del diferencial

- Archivos **nuevos exclusivamente**, sin modificaciones a código ejecutado por el agente.
- Matriz de 18 casos sintéticos que cubre paquetes v2/v3, preguntas de costo, comparación auténtica, precio ya clasificado correctamente, referencias desconocidas o duplicadas, mensaje citado o hipotético, otras solicitudes, selección, necesidad de aclaración y solicitudes de visita.
- Contrafactual: `unittest.mock.patch` reemplaza temporalmente solo `normalize_misread_price_comparison` por una función sin cambios; después se valida la estructura y la evidencia original en `compile_input`.
- Se exige que los cuatro ejemplos erróneos recuperen la misma `Understanding` que un paquete clasificado directamente como `pricing`. También se prueba que, sin el normalizador, sobrevive una comparación incorrecta.
- CI incluye un test del **planificador real** sobre una base SQLite sintética con `prepare_only=True`, que exige una tarea de `pricing` en el camino correcto frente a `catalog`/`comparison` en el contrafactual. No ejecuta herramientas de lectura, envía mensajes ni crea reservas.
- Repetición opcional de paquetes `accepted` de un ZIP sintético anterior, a partir de los registros ya existentes en P2-B.1. Solo se emiten contadores agregados y se omiten paquetes truncados.

## Comandos de validación sin OpenRouter

Desde el contenedor de API desplegado:

```bash
python -m tools.sales_ai.p2b2_mixed_price_selftest
python -m pytest -q tests/test_sales_p2b2_mixed_price_equivalence.py
```

Para ejecutar la matriz y comparar adicionalmente con la batería sintética P1-C.1:

```bash
python -m tools.sales_ai.p2b2_mixed_price_equivalence \
  --bundles /tmp/bp-p2b2-reference.zip \
  --approved-name 'Bay Residence' \
  --output /tmp/bp-p2b2-mixed-price.json
```

El resultado esperado de la matriz es `KEEP_REPAIR`, `safe_to_remove: false`, cuatro casos con diferencias semánticas al desactivar el normalizador. El informe puede incluir `replayable: 7`, `different: 0` al reutilizar la batería anterior: **eso no contradice los cuatro casos dirigidos**, porque la grabación histórica no expuso aquel error. Esta validación no consume tokens.

## Requisitos de seguridad y cierre

1. Ninguna variante puede producir nueva visita, cancelación, cambio de fecha, alerta ni consentimiento de exclusión.
2. La confianza original (`confidence=0.0`) debe permanecer sin modificación.
3. Las respuestas del modelo y las evidencias deben validarse con su mensaje actual exacto; nunca se inventan nombres, fuentes o referencias.
4. Un precio de inmueble no aprobado, una referencia ambigua, preguntas citadas/condicionales o solicitudes adicionales nunca deben activar la reparación.
5. El planificador debe conservar `external_actions=0`, `tool_calls=0` y ninguna reserva en la base de prueba.
6. Los reportes no contienen conversaciones ni `raw_response`.

## Decisión

**P2-B.2 no autoriza eliminación.** El contrato v3 evita muchos errores de clasificación, pero sigue permitiendo el campo `comparison` con un único inmueble. El contrafactual demuestra que la reparación todavía puede ser necesaria. El siguiente esfuerzo debería buscar una simplificación más específica y medir CPU con benchmarks aislados, no atribuir cambios de tokens a este posprocesador.

Esta validación es **sintética y focalizada**. No sustituye pruebas de concurrencia PostgreSQL ni integraciones reales de Calendar/WhatsApp.
