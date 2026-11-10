# Refinamiento de la iteración puntual

Base: `37f960f9dd44e2cca4ceae56c4917cde618758d6`.

## Evidencia que motiva el cambio

La corrida `sales-booking-point-1` produjo cero de las tres reservas esperadas. Las tres conversaciones positivas encontraron horarios, pero la interpretación de una selección explícita omitía las referencias y volvía a buscar el mismo horario. Cuatro mensajes iniciales terminaron en rechazo del contrato. Se observaron también declaraciones de pago tratadas como preguntas, siete días convertidos en plazo de entrega o en una búsqueda de catorce días, y un formato que separaba la cantidad del catálogo como si fuera otro elemento.

## Cambios

- Prompt de interpretación vigente `sales-understanding-prompt/2.14`: selección de cita con referencia local, declaraciones separadas de preguntas, fecha de visita separada de entrega y rechazo neutral separado de frustración.
- Feedback semántico acotado en inferencia del proveedor. Reutiliza el único reintento existente; no añade un bucle ni modifica el resultado del modelo silenciosamente. Los errores tienen códigos de regla específicos. La inferencia inyectada de los antiguos tests conserva su contrato; las pruebas nuevas pasan por la frontera HTTP con respuestas controladas.
- Recuperación conservadora de una elección que reproduce el texto completo de una opción backend vigente y comienza con una elección propia explícita. Solo prepara el resumen. No admite un Yes, una fecha aislada, citas de terceros, negaciones, ordinales discordantes o una opción inventada. Se conservan controles de scope, expiración, disponibilidad y confirmación posterior. Los ordinales abreviados dependen de la referencia interpretada y de su reparación acotada.
- Rango inclusivo de N días a partir de la fecha local actual: `next seven days` se interpreta como hoy y los seis días siguientes. Las opciones muestran fechas concretas para que el comprador seleccione y confirme.
- El formateador mantiene `Last confirmed quantity: 3.` unido.
- El laboratorio toma la referencia temporal después del seed sin redondearla al inicio del minuto, evitando inventario aparentemente futuro. Exporta intentos, reglas y respuestas rechazadas; detiene una tercera selección idéntica sin progreso; verifica avance hacia confirmación, repetición y emoción inventada en el cierre neutral.

No se cambian el modelo publicado, la configuración del staff, los proveedores de mensajería, la base de producción ni las reglas de confirmación. Los avisos de nueva disponibilidad siguen fuera de la validación de esta iteración.

## Nueva corrida

Después del despliegue:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-2
```

Si termina en FAIL/INCOMPLETE, copiar igualmente el resultado. No volver a usar una carpeta no vacía:

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-2/synthetic-sales-results.zip ~/sales-booking-point-2.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-2.zip "$env:USERPROFILE\Downloads\sales-booking-point-2.zip"
```

## Cómo evaluar el siguiente resultado

Comparar el mismo modelo y configuración con la corrida anterior. Priorizar tres reservas reales en la base aislada, selección → resumen → confirmación → reserva, respeto del rango temporal, captura de pago y presupuesto, y ausencia de respaldo inicial. Una regla semántica rechazada debe incluir ahora intentos y motivos en el ZIP. Si todos los controles automáticos pasan, los cierres sin disponibilidad todavía pueden dejar la corrida INCOMPLETE porque requieren revisión humana.

Las pruebas offline verifican los cambios con respuestas controladas; no son una afirmación de que GPT-4o-mini ya supera los seis diálogos. Google Calendar, transporte real, reparto de producción y concurrencia PostgreSQL mantienen las limitaciones documentadas en la entrega anterior.

## Validación realizada

- Regresión completa: 2.557 pruebas aprobadas, 7 omitidas, 0 fallos; 112 módulos cubiertos exactamente una vez en tres shards.
- Matriz de aceptación: 63 PASS, 0 FAIL, 1 NOT_RUN (aceptación real pendiente).
- Pruebas focalizadas previas: 199 aprobadas, incluidas variantes con referencia omitida y reparación semántica inicial.
- No se ejecutó inferencia pagada en esta preparación ni se probó Google Calendar real. La corrida del servidor es la evidencia pendiente de comportamiento del modelo publicado.
