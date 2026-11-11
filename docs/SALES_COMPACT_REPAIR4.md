# Compact Repair 4: solicitudes y selección de horarios

Base: `6a61c35338f880c5ae9f2375844983ee74742ea9`.

## Evidencia

La corrida `sales-compact-repair-3.zip` ejecutó tres casos, 15 turnos y 36 llamadas con el modelo publicado `openai/gpt-4o-mini`, configuración 8. No hubo errores técnicos en esos turnos, pero solo pasó `move_up_B` y no se generaron las dos visitas esperadas. El PDF se interpretó como una comparación. Ambos recorridos de visita ofrecieron horarios, pero al elegir uno la interpretación aceptada cambió a una comparación y nueva solicitud, sin preparar confirmación. Algunos primeros intentos reconocían selección; la reparación de evidencia perdía esa intención.

## Cambios

- Una instrucción literal y única para enviar PDF, fotos o plano de una propiedad nombrada exactamente dentro del catálogo mantiene ese material y su propietario. No crea una visita ni una comparación. Los mensajes mixtos, condicionales, reportados, negativos o con varias propiedades no reciben esta recuperación.
- Una selección completa que coincide con una opción pública del último mensaje del backend conserva `select` y una referencia de cita. No se aceptan IDs del modelo ni se deduce consentimiento de un ordinal aislado. La resolución utiliza el ordinal de la opción exacta previamente comprobada; no interpreta libremente fechas ni duración generadas por el modelo.
- Una solicitud pura de nueva visita no arrastra una comparación inventada. Las comparaciones explícitas o contextuales legítimas siguen usando el recorrido existente; las peticiones mixtas se conservan.
- Se detectan comparaciones no respaldadas en solicitudes de material/visita/selección y directivas de visita respaldadas únicamente por pedidos de material. La validación es acotada: no es una prueba universal de comprensión del lenguaje.
- El prompt explica la diferencia entre material, comparación, solicitud de visita y selección, y pide preservar esa intención durante reparación.
- La evaluación comprueba la entrega de material en el propio turno y la ausencia de comparaciones inventadas en los pasos de acción guionados.

Seleccionar solo prepara el resumen inmutable para confirmar. La creación de cita sigue requiriendo confirmación posterior, autorización y continuidad vigentes, contexto aprobado, opción no vencida y disponibilidad revalidada. No cambia el modelo, las dependencias, el esquema de datos ni SMS/WhatsApp.

## Pruebas

La nueva fixture conserva los paquetes reales de interpretación de la corrida y sus reparaciones. La reproducción usa reloj fijo para comprobar que también se consuman los paquetes reales de selección de fecha, sin sustituirlos por respuestas ideales por un cambio de día. Las respuestas de composición y los mensajes nuevos de confirmación sin paquete grabado usan dobles HTTP locales. Se ejercitan ambos modos de autoflush del laboratorio.

Se comprueban los tres recorridos originales, PDF/galería, dos citas confirmadas solo tras confirmación explícita, rechazo, ausencia de outbox e idempotencia. Hay controles negativos para instrucciones reportadas, condicionales, negadas, varias propiedades y selección sin oferta. También se conserva la comparación legítima junto con una solicitud de visita.

Regresión completa: 2.995 pruebas aprobadas, siete omitidas y cero fallos; 126 módulos cubiertos exactamente una vez en tres shards. Incluye 13 pruebas nuevas de acción y reproducción de paquetes, además de las 52 pruebas previas de consistencia. La prueba de exportación de fallos ahora provoca explícitamente un error de interpretación: no depende de que un proveedor deficiente sea incapaz de progresar con una selección pública exacta. Aceptación técnica: 63 PASS, cero FAIL y una evaluación live pendiente. Estos resultados técnicos no son una nueva medición con el modelo publicado.

## Repetición después de desplegar

Mantener la misma configuración y los mismos tres casos. Se esperan dos visitas; máximo ocho turnos por caso y sesenta llamadas globales (no es un límite en dólares).

SSH:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B unknown_A \
  --max-calls 60 --max-turns 8 \
  --output /tmp/sales-compact-repair-4
```

Copiar incluso si la evaluación termina en `FAIL`:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-4/synthetic-sales-results.zip ~/sales-compact-repair-4.zip
```

PowerShell local:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-4.zip "$env:USERPROFILE\Downloads\sales-compact-repair-4.zip"
```

El laboratorio lee la configuración publicada y hace inferencia real, con SQLite desechable. No escribe leads/citas en producción, no contacta leads ni sincroniza Google Calendar. No valida concurrencia PostgreSQL ni entrega por operador. Los enlaces de recursos del laboratorio no son enlaces de producción.

## Aplicación

Copiar los diferenciales desde la raíz del repositorio, conservando rutas. No hay eliminaciones ni migraciones.

```bash
git pull && git add . && git commit -m "Ground sales material requests and offered slot selections in current lead intent" && git push
```
