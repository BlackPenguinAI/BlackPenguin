# P3-B — Embudo de días y horarios verificados

## Objetivo

Distinguir bloques administrativos de disponibilidad (ventanas) de inicios de
citas verificadas. El agente ya no presenta los primeros tres intervalos de
30 minutos como si fueran todas las alternativas existentes.

## Contrato

1. Consulta sin fecha exacta o con rango de varias fechas: el motor de agenda
   confirma un inicio elegible por día y el agente propone hasta tres días
   distintos. La respuesta indica la propiedad activa y zona horaria.
2. Consulta de un día concreto: se consultan candidatos completos (45 minutos
   por defecto), se eligen hasta tres horarios espaciados y se muestra nombre,
   fecha, hora local y asesor confirmado por la lectura.
3. Respuesta breve al listado de días (`2`, `the second one`, `Saturday`, etc.):
   se resuelve contra un **mensaje saliente entregado y vigente**, su propiedad,
   su orden de días y la oportunidad activa; solo prepara una lectura de slots.
4. Respuesta `Saturday at 11 AM` o solicitud con fecha y hora explícita:
   llega al intérprete habitual y consulta el horario indicado, sin imponer el
   embudo de días; su selección tampoco autoriza por sí sola la reserva.
5. Cualquier selección de slot genera solo una propuesta de visita. La reserva
   requiere confirmación explícita del resumen completo y nueva verificación
   de permisos, agenda, especialista, ámbito y conflicto.
6. Los calendarios conectados y bloqueos de disponibilidad mantienen el mismo
   origen de verdad. No se inventan horarios o fechas.

## Prueba técnica

En GitHub CI, los tres shards y la aceptación deben estar verdes. Las pruebas
unitarias añadidas se encuentran en `backend/tests/test_sales_p3b_visit_funnel.py`.

En API o worker de producción la imagen *no incluye tests/*, así que ejecutar:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.p3b_day_funnel_selftest
```

La prueba es autocontenida: no lee ni escribe SQL, no envía mensajes, no consulta
servicios externos y no crea reservas.

## Casos a probar con lead propio tras CI

- Sin fecha: ofrecer 2–3 días *verificados*, no 10:00/10:30/11:00.
- `the second one`: buscar horarios del segundo día ofrecido y mantener Cleveland.
- `Saturday`: respetar la fecha ofrecida, no recalcular otro sábado.
- `Saturday at 11`: consultar la hora concreta dentro del horario del asesor.
- `What about November 21st?`: continuar la misma visita y propiedad.
- El lead rechaza horarios: abrir una fecha alternativa sin prometer disponibilidad.
- Acepta una hora pero todavía no confirmó resumen: **ninguna reserva**.
- Cambia la propiedad activa: no reutilizar el listado previo de otra propiedad.
- Zona horaria: `America/Denver`, con DST y cambio de día local.

Conservar siempre el lead histórico; utilizar un lead autorizado de prueba para
validación sin alterar reuniones reales.
