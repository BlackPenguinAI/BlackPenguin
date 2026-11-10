# Composición: referencias cerradas por turno y reparación específica

Base: `4199ac5e598ea94c5e7a5b8e3784f019a0c81af8`, flujo desplegado y auditado. Esta entrega no cambia el pipeline, el intérprete, las reglas comerciales ni el evaluador LLM.

## Evidencia

La auditoría aislada capturó nueve respuestas de composición: siete escribían prosa en `paragraphs` y dos utilizaban IDs de perfil/materiales como `evidence_id`. Las respuestas eran JSON válido, pero incumplían el contrato semántico. Son errores distintos del HTTP 400 por `paragraphs` ausente de `required`, ya corregido anteriormente.

## Cambios

- La composición crea un esquema estricto nuevo en cada turno. `blocks[].evidence_id` y los valores de `paragraphs` tienen enums con los IDs de evidencia actuales. `continuation_id` solo permite las continuaciones autorizadas. El esquema no reutiliza referencias de otros turnos ni crea enumeraciones vacías.
- Sin evidencia, `blocks` y `paragraphs` tienen `maxItems: 0`. Con evidencia, se conserva la selección de bloques opcionales y la agrupación explícita o delegada mediante `paragraphs: []`. Los grupos explícitos no pueden estar vacíos.
- El prompt y las descripciones distinguen IDs de evidencia, IDs del contexto y prosa. Los ejemplos muestran IDs, no texto que deba enviarse al cliente.
- El validador local sigue comprobando evidencia requerida, referencias desconocidas, duplicados, orden del catálogo y autorización de la continuación. Los enums del proveedor no reemplazan esas comprobaciones.
- Los fallos tienen códigos estables: `unknown_evidence`, `duplicate_evidence`, `missing_evidence`, `unauthorized_continuation`, `catalog_order`, `paragraph_reference`, `paragraph_coverage`, `empty_paragraph`, `response_size` y `schema_validation`.
- El único reintento recibe la regla concreta, localización, referencias permitidas/requeridas y un ejemplo válido para el turno. Conserva el límite de dos intentos y el presupuesto temporal anterior; no reejecuta herramientas ni concede nuevas acciones.
- La traza incluye `reference_contract` y, por intento, `rule_code`, `rule`, `validation_issues` y `selection`. Solo se guardan referencias/enums conocidos literalmente. Strings desconocidos se representan mediante hash y longitud; no se guarda la respuesta cruda ni mensajes de validación que puedan contener texto privado. Los errores HTTP conservan su diagnóstico saneado anterior.
- El probe sintético utiliza también un esquema ligado a sus referencias e0/none.

El renderizador continúa siendo el propietario del texto factual y de los enlaces. No se acepta prosa arbitraria para evitar el respaldo, ni se convierten IDs de materiales/perfil en IDs de evidencia automáticamente.

## Aplicar

Copiar `backend/` y `docs/` del ZIP diferencial a la raíz. No hay eliminaciones, dependencias nuevas, migraciones ni cambios de prompts publicados. Esperar a que el pipeline despliegue el mismo commit en API y worker.

Primera comprobación real, sin el juez que todavía tiene criterios pendientes de corregir:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.evaluation \
  --company-id a73df3b4-95fa-4ed4-bb2c-bfe3543dfa4b \
  --project-id 854ac168-1b0b-5ef3-a68e-091b5cc82e0f \
  --mode replay --max-calls 80 --no-judge \
  --output /tmp/sales-evaluation-references-1
```

Es una evaluación con el modelo real, con consumo en OpenRouter, dentro del aislamiento existente: sin mensajes SMS/WhatsApp ni escrituras en producción. Utilizar un directorio nuevo en cada ejecución.

```bash
docker cp bp_api_prod:/tmp/sales-evaluation-references-1/report.json ./sales-evaluation-references-report.json
```

Desde PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-evaluation-references-report.json "$env:USERPROFILE\Downloads\sales-evaluation-references-report.json"
```

Conservar el informe anterior para comparar. En turnos que alcancen composición, buscar `output.metadata.composition.status: accepted`. Si se rechaza otra selección, el informe identifica ahora la regla y los IDs permitidos; no hace falta el hook temporal de auditoría para localizarla.

El resultado global puede continuar en FAIL por los problemas separados de comprensión/captura de presupuesto, efectivo, documentos, estacionamiento o peticiones múltiples. STOP y fotos también requieren ajustes independientes de los criterios del juez. Esta entrega no afirma resolverlos.

## Validación

- 221 pruebas aprobadas: referencias de composición, cliente HTTP, evaluación aislada, entregas 3/4 y grupo B. Incluyen reparación real del coordinador de composición con inferencia simulada, fallback acotado, rechazo de texto privado y compatibilidad de orden/bloques opcionales.
- Nueve patrones de fallo de la auditoría convertidos en regresiones con datos sintéticos.
- Validación adicional independiente con JSON Schema Draft 2020-12: los nueve esquemas ligados al turno son válidos; rechazan las nueve respuestas originales y aceptan nueve ejemplos corregidos.
- `git diff --check` correcto.
- No se modificaron registros ni se contactaron proveedores/leads durante preparación. No hubo inferencia real. Las pruebas no garantizan que todos los proveedores apliquen todas las restricciones: permanece la validación local y la comprobación pendiente con el replay del modelo real.

Referencias técnicas: https://developers.openai.com/api/docs/guides/structured-outputs y https://github.com/OpenRouterTeam/docs/blob/main/guides/features/structured-outputs.mdx.
