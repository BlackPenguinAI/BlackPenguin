# Iteración puntual: reparación de interpretación y zona del proyecto

Base: `7872e7d9a76ad9c1a045d32b294e2792a2a98cb1`. Se mantienen los seis casos, el modelo publicado y las reglas de confirmación de visita.

## Problemas observados en la corrida 2

Se crearon las tres reservas esperadas, pero cuatro mensajes iniciales fueron rechazados: el primer intento omitía la declaración de pago y el reintento inventaba citas al añadir I o puntuación. En dos casos `project timezone` se intentaba usar como identificador IANA. Una negativa neutral se clasificaba como frustración y su reparación repetía la emoción. Además, los guiones negativos afirmaban que esperarían nuevos horarios sin que el agente hubiera explicado su ausencia.

## Solución

- Las referencias explícitas a la zona del proyecto o propiedad se resuelven con la zona publicada. Se conserva la precedencia de una zona IANA explícita y se rechazan identificadores inválidos.
- El único reintento existente limita las evidencias de solicitudes y preferencias mediante opciones literales del mensaje original en el esquema JSON. El parser de evidencia exacta no se relaja, no se reconstruyen citas inventadas ni se crean preferencias desde el guion.
- Se conserva en el feedback la instrucción de corregir los campos afectados sin descartar información válida de visita y declaraciones. La traza identifica el esquema de reparación y los motivos de rechazo.
- Una emoción opcional sin sustento en una negativa neutral puede omitirse con un registro explícito de normalización. Se preservan solicitudes, restricciones, negativa y consentimiento; no se concede ninguna autorización nueva. No se agrega otra llamada al modelo por esa emoción opcional.
- El comprador guionizado solo agradece la falta de disponibilidad después de una respuesta que la explica. Frente a un respaldo o una pregunta improcedente aclara su solicitud. Una oferta inesperada en un escenario negativo se reporta, sin aceptarla automáticamente.
- Prompt vigente: `sales-understanding-prompt/2.15`. La versión de configuración del staff puede seguir siendo 8: son identificadores distintos.

## Próxima corrida

Después del despliegue:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-3
```

Aunque termine en FAIL o INCOMPLETE, copiar:

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-3/synthetic-sales-results.zip ~/sales-booking-point-3.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-3.zip "$env:USERPROFILE\Downloads\sales-booking-point-3.zip"
```

Usar otra carpeta vacía si se repite la corrida. 120 es un límite de llamadas, no un límite monetario. Las reservas y los usuarios siguen aislados de producción; no se envían mensajes ni se crean eventos externos.

## Criterios de comparación

Esperamos conservar tres reservas válidas e idempotentes, reducir los respaldos iniciales y llegar a una explicación real de falta de disponibilidad en los tres escenarios negativos. Revisar `interpretation_attempts`, sus reglas, `quotation_schema` y `normalizations`. Las comprobaciones de cierre que requieren revisión humana pueden mantener INCOMPLETE aun sin fallos automáticos.

Los controles de selección de la entrega anterior se mantienen. Las pruebas offline no demuestran que el modelo publicado supere los diálogos. Tampoco acreditan integración Google Calendar, transporte real, reparto de producción ni concurrencia PostgreSQL.

## Validación realizada

- Regresión completa: 2.569 pruebas aprobadas, 7 omitidas y 0 fallos; 113 módulos cubiertos exactamente una vez.
- Matriz de aceptación: 63 PASS, 0 FAIL, 1 NOT_RUN (aceptación real pendiente).
- Batería focalizada previa: 119 aprobadas. Las variantes adicionales de zona posesiva y local se incluyeron después en la regresión completa.
- Pruebas HTTP controladas verifican la reparación con esquema de citas restringidas y la omisión auditada de emoción neutral sin llamada adicional. No se ejecutó inferencia pagada durante la preparación.
