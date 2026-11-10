# Iteración puntual 4: conservar declaraciones y evitar preguntas inventadas

Base: `93c1b298c566e89d0667cfc3f118abbf070a804f`. Modelo y configuración del staff se mantienen. Prompt de interpretación: `sales-understanding-prompt/2.16`.

## Problemas que resuelve

La corrida 3 reservó las tres visitas esperadas, pero la reparación omitía presupuestos válidos y transformaba declaraciones de presupuesto/pago o disponibilidad para visitar en solicitudes de inventario. El primer intento podía fallar por evidencia y el segundo descubrir recién los errores de significado. El texto de disponibilidad hablaba de catorce días aunque el rango efectivo fuera de siete, y el cierre sugería que el comprador no estaba listo.

## Cambios de interpretación

- Se separa la decodificación estructural de la comprobación final de evidencia. Cuando la estructura es válida pero una cita es incorrecta, el diagnóstico puede incluir también los errores semánticos, sin autorizar efectos de negocio de ese resultado.
- Durante el único reintento se conservan omisiones de declaraciones actuales verificadas de forma independiente. El alcance es deliberadamente estrecho: presupuesto propio con importe y moneda coincidentes y pago al contado inequívoco. No se trasladan solicitudes, referencias, visitas ni consentimientos. Declaraciones ambiguas, reportadas, condicionales o con retirada no se conservan automáticamente.
- No se sobrescribe una preferencia que el reintento haya incluido ni una retirada. La interpretación completa debe seguir pasando el contrato y la evidencia exacta antes de usarse.
- Una frase que solo declara presupuesto/pago o disponibilidad temporal para visitar puede retirarse de las solicitudes de información inventadas por el modelo. Se registra la normalización. No se modifica una exclusión ni una solicitud vinculada a alternativas o comparaciones; las preguntas genuinas no coinciden con estas reglas de declaración completa.
- Las normalizaciones aparecen en `interpretation_attempts[].normalizations`, incluidas `restore_verified_current_declaration` y `omit_question_invented_from_declaration`.

## Evaluación y textos

El laboratorio exporta el perfil comercial leído de nuevo desde la base aislada después de cada turno. Comprueba presencia de presupuesto y pago en la interpretación inicial, presupuesto de 900.000 USD en el perfil guardado y ausencia de solicitudes inventadas desde declaraciones. Puede mostrar más fallos que antes aun reservando: los nuevos controles detectan defectos que no se medían.

La oferta sin disponibilidad comunica las fechas realmente revisadas. Si la búsqueda cubre solo parte de un rango largo, distingue esa parte de la preferencia completa que se propone guardar. El cierre ofrece revisar nuevos horarios después, sin atribuir el problema a la disposición del comprador ni afirmar que ya existe un aviso programado.

## Ejecución después del despliegue

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-4
```

Aunque termine en FAIL o INCOMPLETE, copiar los resultados:

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-4/synthetic-sales-results.zip ~/sales-booking-point-4.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-4.zip "$env:USERPROFILE\Downloads\sales-booking-point-4.zip"
```

Usar una carpeta nueva en cada corrida. Se mantienen seis casos, un máximo global de 120 llamadas y un único reintento por interpretación. El límite es de llamadas, no monetario. No se usa modelo comprador ni juez. No se envían mensajes ni se crean citas en calendarios reales.

## Qué revisar

Conservar las tres reservas correctas y únicas, comprobar presupuesto y pago persistidos sin preguntas adicionales no solicitadas, verificar cero respaldo inicial y revisar los tres cierres sin disponibilidad. Registrar cuántos primeros intentos necesitan reparación: las normalizaciones no demuestran una comprensión inicial correcta del modelo.

La calidad del modelo publicado se comprobará en esa corrida. Google Calendar, transporte real, reparto de producción y concurrencia PostgreSQL mantienen las limitaciones de las entregas anteriores. Los tres cierres marcados para revisión humana pueden dejar el resultado INCOMPLETE aunque no existan fallos automáticos.

## Validación realizada

- Regresión completa: 2.578 aprobadas, 7 omitidas, 0 fallos; 114 módulos cubiertos exactamente una vez.
- Matriz de aceptación sobre la versión final: 63 PASS, 0 FAIL, 1 NOT_RUN.
- Pruebas focalizadas comprueban conservación de presupuesto ante omisión en el reintento, persistencia del importe y moneda en el perfil, diagnóstico semántico aun con citas rechazadas, respeto de retiradas y ausencia de preguntas inventadas desde declaraciones puras.
- Una aserción que esperaba el texto anterior de falta de disponibilidad fue actualizada. Se repitió el shard afectado y la aceptación, conservando los controles de ausencia de reservas/avisos sin permiso.
- No se ejecutó inferencia pagada durante la preparación. La calidad del modelo publicado queda pendiente de la corrida 4.
