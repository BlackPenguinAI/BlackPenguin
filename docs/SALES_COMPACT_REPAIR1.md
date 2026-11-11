# Corrección 1 de la batería compacta

Base desplegada: `1cd37eed349b15db0953cf0f52298ae27be353b0`.

El experimento recibido ejecutó 63 turnos del flujo `sales-current/1.0`, usando `openai/gpt-4o-mini`, configuración publicada 8. Se crearon 3 de 8 visitas esperadas. Ninguna de las cinco solicitudes de visita en proyectos con varios tipos de propiedad logró avanzar. En las interpretaciones aceptadas faltaban referencias a propiedades nombradas explícitamente; las tres visitas exitosas correspondían al proyecto con un solo tipo. No se observaron errores HTTP finales y las 53 composiciones fueron aceptadas, pero interpretar un JSON válido no garantizó responder correctamente.

## Cambios

- El intérprete conserva un nombre exacto y único del catálogo del project actual y lo vincula a una solicitud existente que lo menciona. No crea solicitudes, directivas de visita, horarios, consentimientos ni confirmaciones. La anotación queda en `normalizations` como `bind_exact_current_scoped_property`.
- Las referencias ambiguas, comparaciones, negativos, discurso atribuido, nombres parecidos y códigos de unidades individuales no se convierten automáticamente en selección de un tipo de propiedad. No se utilizan nombres de otros projects para resolver una referencia.
- Una motivación propia y explícita reconocible que falta, o queda como texto libre sin clasificación, produce feedback para la reparación existente, limitada a un reintento. El modelo conserva la cita literal y propone un segmento del contrato; no se deduce de edad, ocupación ni otros datos demográficos. Una ambigüedad real admite aclaración.
- El prompt de interpretación `sales-understanding-prompt/2.22` destaca referencias, motivaciones, comparaciones, consultas compuestas y separación de inversión versus financiación. El modelo publicado no se cambia; no requiere volver a publicar AI Settings.
- Se conservan las preguntas independientes de precio y disponibilidad. Si la interpretación omite disponibilidad de una pregunta explícita por ambas, se solicita corregirla.
- Una pregunta sobre rentabilidad/ocupación no se acepta como consulta de préstamo. La respuesta aclara la ausencia de cifras publicadas cuando corresponda y que no se pueden garantizar rendimientos. No se convierte un objetivo de ROI en garantía ni se inventan porcentajes. Los términos específicos pueden revisarse durante una visita.
- Los nombres conocidos del proyecto se excluyen de la muestra usada para detectar idioma. Esto permite preguntas inglesas como `Is Summit Villa available?`; las cláusulas españolas circundantes siguen bloqueadas por la política vigente de inglés.
- Se emite una sola advertencia común de precio/disponibilidad al comparar alternativas. Cuando ya se entregó el recurso solicitado, no se presenta otro PDF como si aún faltaran las fotos. Las ofertas complementarias y alternativas para necesidades pendientes conservan su revisión y consentimiento.
- La evaluación de rentabilidad ya no acepta `rent` dentro de `current` ni un descargo de financiación como respuesta pertinente. Los casos offline de la batería dejan de tolerar los fallos conocidos que esta entrega corrige.
- Las pruebas consultan la versión vigente del prompt en lugar de mantener números duplicados que bloqueen futuras actualizaciones de versión.

Los cambios son del backend. No hay migraciones, cambios de dependencias ni alteraciones a la configuración del modelo. Se conservan los controles de tenant, autorizaciones y confirmación posterior de citas. Crear una referencia a una propiedad no autoriza reservarla ni agendar sin confirmar.

## Pruebas y límites

Las respuestas JSON reales del experimento se conservan en `tests/fixtures/sales_ai/compact_battery_1_interpretations.json`: contienen solo mensajes y estructuras sintéticos, sin credenciales, teléfonos reales ni tokens públicos. Las pruebas reproducen esas respuestas incompletas y, cuando se requiere reparación, usan un proveedor HTTP simulado que responde al feedback. El motor, la base, la resolución de propiedades, las aprobaciones de materiales y el agendamiento son reales dentro del laboratorio.

Este replay acredita el tratamiento de las omisiones observadas y la ejecución del core; no acredita que el modelo publicado vaya a responder siempre correctamente al prompt nuevo. No se han realizado inferencias pagadas durante la preparación. La siguiente corrida mide ese comportamiento. Se mantiene el mismo modelo para poder comparar el efecto de la corrección.

## Primera evaluación tras desplegar: ocho casos afectados

Esta selección incluye cuatro visitas esperadas, cambio de propiedad, falta de fotografías, inventario agotado, rentabilidad, motivación y falta de slots. No equivale a ejecutar los 16 casos completos.

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B downsizing_B rental_B resale_A portfolio_A portfolio_B unknown_A \
  --max-calls 160 --max-turns 8 \
  --output /tmp/sales-compact-repair-1
```

Incluso si termina con `FAIL` o código 2, copiar los resultados con un comando separado:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-1/synthetic-sales-results.zip ~/sales-compact-repair-1.zip
```

PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-1.zip "$env:USERPROFILE\Downloads\sales-compact-repair-1.zip"
```

Adjuntar el ZIP completo. Se compararán las referencias y motivaciones conservadas, recursos entregados, repeticiones, idioma, pertinencia de las respuestas y visitas creadas. El costo real queda en `provider_usage`; 160 es un límite de llamadas, no de dólares.

## Batería completa posterior

Después de analizar la selección y cerrar los fallos que persistan:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 320 --max-turns 8 \
  --output /tmp/sales-compact-battery-2
```

Esta corrida espera ocho visitas y cero citas en los ocho casos que no deben agendar. Se mantienen las limitaciones del laboratorio: base temporal, cero contactos a leads reales, sin WhatsApp/SMS, Google Calendar, locks PostgreSQL ni round-robin de producción. Los links del laboratorio no funcionan contra producción después de eliminarse la base; las copias de PDFs y galerías están en el ZIP.

## Aplicación

Extraer el ZIP diferencial en la raíz del repositorio, respetando `backend/` y `docs/`.

```bash
git pull && git add . && git commit -m "Preserve explicit sales subjects and repair incomplete lead interpretations" && git push
```

## Validación técnica

- 2,844 pruebas aprobadas y 7 omitidas en los tres shards del backend; 123 módulos cubiertos exactamente una vez.
- Aceptación técnica: 63 PASS, 0 FAIL, 1 NOT_RUN (aceptación con modelo real pendiente).
- 230 pruebas dirigidas aprobadas sobre interpretación, batería compacta, materiales y agenda. Se incluyeron además controles de discurso atribuido/unidades y se repitieron 107 pruebas de completitud/política comercial, incluyendo consultas mixtas de rentabilidad y financiación.
- Los 16 guiones cumplen sus comprobaciones offline, con ocho visitas creadas, tanto con `autoflush=False` como con `True`. Esto usa HTTP simulado y reparación guiada por el contrato; no es un resultado de calidad del modelo publicado.
- Sin llamadas pagadas, contactos a leads ni escrituras en producción durante la implementación. Los tests PostgreSQL que requieren infraestructura se mantienen en CI.
