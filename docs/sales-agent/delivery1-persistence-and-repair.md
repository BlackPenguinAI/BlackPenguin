# Entrega 1: persistencia y reparación con sesiones de producción

Base: `6b8cc900678d3a7c1f11f01562c689783cfd6cbb`. Prompt vigente: `sales-understanding-prompt/2.17`. Se mantienen modelo, configuración publicada y los seis escenarios de iteración puntual.

## Causa confirmada

Después de capturar el perfil y componer la respuesta, `active_service` relee el lead mediante `_current`, que usa `populate_existing()` para verificar permisos y estado actual. Con `SessionLocal(autoflush=False)`, esa lectura reemplazaba atributos pendientes, incluyendo presupuesto, financiación e inteligencia comercial, con valores anteriores de la base. La captura quedaba registrada en la traza pero desaparecía antes del commit. Los tests anteriores usaban el autoflush predeterminado y no reproducían esa diferencia.

## Corrección

Se hace `flush([lead])` dentro de la transacción existente antes de la relectura de autorización. No se cambia el autoflush global ni se adelanta el commit. Las comprobaciones de alcance, control humano, baja y publicación permanecen. Un turno interrumpido sigue haciendo rollback, incluso de los cambios ya enviados por el flush.

El laboratorio relee el perfil después del commit desde una sesión ORM nueva con autoflush desactivado. El reporte declara `profile_read_mode: new_session_after_commit` y la configuración `session_autoflush`. Las pruebas del piloto se ejecutan con autoflush falso y verdadero, incluida la persistencia después de otro mensaje y la idempotencia de las reservas.

## Reparación de interpretación

- Las opciones de citas literales se aplican también a directivas y campos anidados `*_evidence`, incluidos fecha, hora y zona. Las ramas nulas siguen permitidas. Las citas temporales históricas no pueden presentarse como evidencia del mensaje actual; las preferencias guardadas se usan por separado.
- Las citas válidas presentes en el resultado rechazado tienen prioridad al construir las opciones de reparación, conservando fragmentos como `project timezone` si existen en el mensaje actual.
- Las declaraciones puras de contado que el modelo etiquete como preguntas de financiación pueden omitirse como solicitudes inventadas, con auditoría y conservando preferencias. No se retiran preguntas genuinas como `Do you accept cash?`.
- Cash/contado describe financiación declarada por el comprador sin préstamo, no dinero físico, pago en el chat ni fondos verificados.

Esto no incorpora todavía las reglas comerciales ampliadas de las siguientes entregas ni añade llamadas de un comprador o juez LLM. Se conserva un único reintento.

## Corrida posterior al despliegue

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite booking-point \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 120 --max-turns 8 \
  --output /tmp/sales-booking-point-5
```

Aunque termine en FAIL o INCOMPLETE, copiar los resultados:

```bash
docker cp bp_api_prod:/tmp/sales-booking-point-5/synthetic-sales-results.zip ~/sales-booking-point-5.zip
```

PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-booking-point-5.zip "$env:USERPROFILE\Downloads\sales-booking-point-5.zip"
```

Usar una carpeta nueva si se repite. El límite de 120 corresponde a llamadas, no a moneda. No se envían mensajes reales ni se crean eventos externos.

## Criterios de revisión

Tres reservas válidas, confirmadas e idempotentes; presupuesto y financiación presentes en la interpretación y en el perfil de la sesión nueva; ausencia de citas históricas usadas como actuales; y falta de disponibilidad explicada sin bucles de respaldo. La evaluación del modelo real sigue siendo independiente de las pruebas offline con respuestas controladas. Google Calendar, canales reales y concurrencia PostgreSQL mantienen las limitaciones anteriores; los cierres sin disponibilidad requieren revisión humana.

## Validación realizada

- Regresión completa: 2.604 aprobadas, 7 omitidas, 0 fallos; 115 módulos cubiertos exactamente una vez.
- Aceptación: 63 PASS, 0 FAIL, 1 NOT_RUN (validación real pendiente).
- 68 pruebas focalizadas previas cubren ambos modos de autoflush, nuevos lectores después del commit, continuación del diálogo, seis escenarios con proveedores controlados, rollback de perfil y ausencia de envío ante interrupción, y rechazo de evidencia temporal histórica.
- No se ejecutó inferencia pagada durante esta preparación. La corrida 5 aportará la evidencia del modelo publicado.
