# Sales AI — Grupo B, pasos 3 y 4

Fecha: 8 de noviembre de 2026. Base: `f1b16f1fd3f1c77c5dc5283b88879c433fb90411`.
Rama: `sales-ai/group-b-configuration-english`. Continúa A y su corrección de Actions.
Siguiente entrega autorizable: **C, pasos 5 y 6**. Los resultados están en `group-b-report.json`.

## Alcance y activación

Se implementa la configuración comercial por turno y la puerta de inglés del nuevo
runtime activo. No se publica ningún prompt, no se cambia el modelo configurado
(`openai/gpt-4o-mini` en el snapshot), no se ejecutan migraciones ni se despliega.
Los siguientes grupos siguen pendientes; esta entrega no acredita el recorrido
comercial completo, la reprogramación ni la calidad de respuestas del modelo real.

El código nuevo requiere **ambas** variables de plataforma:

```dotenv
SALES_NEXT_FLOW_ENABLED=true
SALES_NEXT_FLOW_PROJECT_IDS=<UUID-del-proyecto-de-prueba>
```

Los valores predeterminados son `false` y una lista vacía. La lista acepta UUID
canónicos separados por coma; una lista vacía, `*`, `all` o cualquier elemento
inválido no selecciona proyectos. Además, el runtime estructurado existente debe
estar habilitado y seleccionar esa oportunidad mediante su configuración vigente
(`SALES_DIALOGUE_RUNTIME_ENABLED` y `runtime_config`). Estos controles no se
convierten en instrucciones editables por el modelo. No activar globalmente para
presentar este grupo como el flujo final. Se mantienen los mecanismos existentes de
consentimiento, control manual y autorización de las propiedades.

La ruta anterior y el simulador que usa su grafo conservan su contrato; las pruebas
de B entran por `process_live_inbound`, la misma coordinación de SMS/WhatsApp.
Para probar B en interfaz se debe usar esa ruta/cohorte, no asumir que el simulador
anterior ya representa el nuevo agente.

## Paso 3 — Configuración comercial por turno

`turn_configuration.resolve` lee sin insertar defaults, hacer flush, commit o publicar:

| Información | Fuente y uso |
|---|---|
| Identidad y guardrails | Campos existentes de Agent Sales, como contexto de referencia |
| Protocolo comercial | `sales_playbook.conversation_protocol`, con compatibilidad comercial explícita si falta |
| Etapa | `lead.pipeline_stage` y su clave en `stage_prompts` |
| Segmento | `lead.assigned_segment` y su clave en `segment_prompts` |
| Objeciones | Hasta tres objeciones abiertas persistidas del mismo lead y `objection_prompts` |
| Guía de interpretación | `runtime_config.understanding_guidance` como referencia |
| Contrato técnico | Esquema estricto, permisos, políticas e intérprete definidos en backend |

No se inventan segmento ni objeciones para escoger un playbook. Los valores conocidos
del lead pueden evolucionar; el resolver vuelve a leerlos en cada turno. La publicación
es una fotografía coherente: un override de Company necesita una versión Sales
publicada; en caso contrario se conserva la publicación global. Si la configuración
global histórica no tiene versión, se identifica como `legacy_active_config`, con
hash y versión desconocida. Publicaciones duplicadas se rechazan con diagnóstico.
Una edición todavía no publicada no sustituye la versión publicada.

El intérprete nuevo usa `sales-understanding-prompt/2.0`. Excluye `protocol_prompt`
del contexto del modelo porque mezcla instrucciones comerciales y el JSON anterior;
conserva su hash de compatibilidad. No modifica ese campo en DB. Identidad, etapa,
segmento y objeciones se transmiten como datos de referencia: no pueden modificar
el esquema, el idioma, permisos, herramientas, consentimiento ni transacciones.
El runtime, scoring y cadencias existentes conservan sus controles de backend;
los playbooks no conceden permisos. La composición comercial avanzada corresponde
a los grupos posteriores: B incorpora las guías al intérprete y deja su contrato
disponible para el futuro compositor, sin afirmar que este ya usa un nuevo LLM final.

La traza guarda ID de configuración, Company propietaria, versión publicada,
fecha, hash, divergencia con la edición activa, y procedencia de etapa/segmento/
objeciones. Cada texto de guía tiene límite de tamaño y se registra su truncamiento;
se conserva el límite total de contexto del intérprete.

### Borrador compatible, sin publicación automática

La API de AI Settings acepta el campo opcional `sales_playbook`. Los campos
personalizados existentes siguen siendo la fuente de identidad y playbooks; no se
crea una segunda copia de estos mapas que pudiera quedar desactualizada.

Con una exportación **solo del pack `agent_ventas`**, sin credenciales ni wrapper:

```bash
cd backend
PYTHONPATH=. python -m tools.sales_ai.draft_playbook \
  --input /tmp/sales-agent-pack.json \
  --output /tmp/sales-agent-proposal.json
```

La herramienta es local, no abre DB ni red y exige un archivo de salida nuevo.
Produce `DRAFT_NOT_PUBLISHED`, preserva modelo, scope, mapas y protocolo original,
y añade la propuesta de protocolo comercial. Debe revisarse su contenido antes de
una publicación explícita mediante el mecanismo existente. No se suministra ningún
comando que publique o habilite el flujo en producción.

### Restricciones explícitas por acción

El nuevo camino deja de usar coincidencias de texto libre como compilador de
políticas. Reutiliza los registros de gobernanza `sales_action_policy`, aprobados
por Admin/Assistant activos de la misma Company, con fecha de aprobación y versión.
Los endpoints existentes `/api/v1/governance/guidance` conservan su autorización y
scoping. Esta edición se gestiona mediante API; no se añade un editor JSON a la UI.
Los registros técnicos no se mezclan con FAQ/scripts del contexto general.

Ejemplo de **contenido** para revisión administrativa, no política ya aprobada:

```json
{
  "version": "sales-action-policy/1.0",
  "source_note_sha256": "<hash de las notas aprobadas que revisó el administrador>",
  "rules": [
    {
      "id": "financing-approval",
      "topics": ["financing"],
      "effect": "require_review",
      "reason": "Financing terms require Sales verification."
    }
  ]
}
```

`effect` admite `require_review` o `deny`; no admite `allow`, permisos o instrucciones
de sistema. Las restricciones Company y Project se acumulan; Project nunca levanta
una restricción Company. Se registra evidencia de aprobador, registro, versión,
scope, motivo y hash. Pricing/inventory también protegen catalog/property_details
porque esos resultados contienen precios y cantidades.

Las notas libres aprobadas que aún no tienen una revisión estructurada coincidente
quedan como `explicit_policy_review_required`; una revisión inválida como
`invalid_review_record`. Hasta aclararlas se retienen las afirmaciones/acciones
comerciales no autorizadas, se informa que Sales verificará esa parte y se mantiene
el chat abierto. No se pausa por la sola existencia de notas. Una revisión explícita
con `rules: []` puede documentar que las notas revisadas no añaden restricciones;
no elimina reglas Company ni sustituye la autorización de datos. Un cambio de notas
invalida la coincidencia de su revisión anterior. Se conservan las restricciones
anteriores hasta archivarlas mediante la autorización administrativa existente.

El hash es SHA-256 del JSON canónico de las notas (`sort_keys=True`, `ensure_ascii=False`);
la misma función `turn_configuration.digest` lo calcula. El valor pendiente se expone
en `action_policy.unresolved[].source_note_sha256` de la traza. No convertir notas
automáticamente en políticas ni aprobar reglas vacías sin revisión humana.

## Paso 4 — Inglés exclusivamente

Orden: alcance/consentimiento/control manual → bajas y seguridad verificadas → idioma
→ interpretación y acciones comerciales → validación de salida → despacho y recibo.
Los controles explícitos en español también tienen prioridad sobre el idioma.

Una consulta sustancial en otro idioma recibe exactamente en inglés:

> This conversation is currently available in English. Please re-enter your question in English.

Esa respuesta no invoca al modelo, no cambia selección, preferencias, restricciones
o tareas, no reserva ni emite enlaces. No crea una pausa ni intervención humana por
idioma. Se registra la decisión; el recibo puede incrementar la revisión de auditoría
sin cambiar el estado comercial. No se agenda seguimiento comercial automático
mientras se espera esa reformulación. Una respuesta posterior en inglés retoma el flujo.

Se aceptan nombres y códigos exactos del contexto aprobado, números, horas y frases
inglesas habituales. Un asentimiento neutral corto solo se acepta con una pregunta/
oferta contextual; por sí solo nunca autoriza una reserva. Las ofertas anteriores
se conservan durante la reformulación, con su mensaje original y expiración original.
Una respuesta manual sigue reemplazándolas. No se copian ofertas a una fecha nueva.

La detección usa `langdetect==1.0.9`, perfiles locales incluidos en la dependencia,
una instancia con semilla fija y un vocabulario acotado para la ambigüedad de textos
ingleses breves. No hace llamadas externas ni clasifica la intención comercial por
palabras. La detección estadística puede equivocarse; su incertidumbre solicita
reformulación, nunca pausa. Véase la documentación primaria:
https://github.com/Mimino666/langdetect. No se implementa atención multilingüe.

Una salida no inglesa se descarta **antes** de confirmar efectos y se revierte la
transacción propuesta, conservando referencia de configuración/hash para diagnóstico.
El despacho automático añade una segunda comprobación, incluida la cadencia. Los
mensajes humanos conservan su texto. El primer WhatsApp requiere su plantilla
aprobada en inglés; una plantilla con cuerpo no inglés genera un error de configuración
antes de enviar, sin convertirla en un mensaje libre no aprobado. El primer SMS
automático también tiene comprobación de inglés.

El idioma de nombres propios se conserva. Si datos aprobados contienen prosa comercial
en otro idioma que el compositor actual no convierte, B emite una respuesta inglesa
segura. La generación comercial natural con esos datos se valida en el grupo E;
no se da por demostrada con estas pruebas de contrato.

## Verificación y límites

```bash
cd backend
python -m pip install -r requirements.txt
BP_PYTHON=python bash tools/sales_ai/offline.sh group-b
BP_PYTHON=python bash tools/sales_ai/offline.sh baseline
BP_PYTHON=python bash tools/sales_ai/offline.sh replay /tmp/group-a-replay.json
```

Las pruebas B incluyen las seis propiedades/proyectos exportados en ambos canales:
24 turnos por el coordinador real, una solicitud española y otra inglesa por cada
proyecto/canal. No alteran notas ni inventan aprobaciones reales. Los tests de políticas
usan registros y revisores sintéticos identificados como tales. Se conservan los
precios, monedas, estados y zonas horarias del fixture; no se corrige silenciosamente
el precio `30.00 USD` de Fouquet’s ni se inventan contenidos de materiales.

También se prueban publicación por turno, no escritura al leer, preservación del
borrador, límites de ámbito, STOP/seguridad/control manual, reintentos sin duplicación,
rollback de enlaces, continuidad de ofertas y vencimiento de horarios. Las respuestas
LLM y los proveedores son inyectados/simulados: no acreditan calidad de venta del
modelo real, mensajes entregados al teléfono ni aceptación end to end de T01–T26.

No hay Docker en el entorno local. Se comprueba además una copia física aislada de
los `COPY` del Dockerfile y los montajes de pruebas/referencias de Actions, con la suite
completa, sin resolver imports desde el checkout. El build real de imagen y el siguiente
run remoto de Actions siguen siendo validaciones del despliegue, no realizadas aquí.
