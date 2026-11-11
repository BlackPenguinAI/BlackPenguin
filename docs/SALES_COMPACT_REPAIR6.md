# Repair 6: elección explícita de propiedad y material anafórico

Base: `88d2e6b` (guía visual posterior al runtime Repair 5 `4fb1707`).

## Problema observado

Repair 5 completó dos visitas, pero falló `move_up_B`. El primer paquete reconoció Cedar Loft y solicitó fotos, con confianza 1, pero agregó una visita sobre “Please send its photos”. La validación lo rechazó. El segundo paquete cambió el dueño a tipo material, con confianza 0; la conversación terminó en aclaración y sin galería. Independientemente, el check inicial de alcance exigía `property_catalog_offer` aunque el primer turno era una respuesta válida de `property_details` sobre Cedar Studio.

## Corrección

- Reconocer una elección literal, actual y única de propiedad seguida de petición de su material. Enlazar las dos cláusulas dentro del mismo mensaje y corregir el propietario/selección; no usar historia como una nueva elección.
- Eliminar la visita no solicitada en esa petición pura de elección/material. No subir la confianza ni borrar restricciones, alternativas, retiros, cancelaciones u otras intenciones para forzar una entrega. Los permisos de recurso y las guardas del core siguen vigentes.
- Mantener la ruta acotada: mensajes negativos/reportados/hipotéticos, varios nombres, ámbito ajeno, formato contradictorio o acciones mezcladas no obtienen esta recuperación automática.
- El evaluador acepta catálogo explícito o metadata de detalles resuelta al ID correcto, exige que la respuesta mencione la propiedad pedida y rechaza otras propiedades. Se conservan los resultados históricos originales.

Las 20 nuevas pruebas incluyen paquetes de los tres diálogos reales de Repair 5, primer intento de switch aceptado sin gastar reparación, galería entregada, dos visitas después de confirmación e idempotencia, más variantes y negativos. No cambia el modelo/configuración ni hay migraciones o dependencias nuevas.

## Validación

Regresión: **3.023 PASS, siete SKIP, cero FAIL**; 128 módulos cubiertos exactamente una vez en tres shards. Aceptación técnica: 63 PASS, cero FAIL, una live pendiente. Las 20 específicas forman parte de ese total; no se suman de nuevo. No se hicieron llamadas pagadas localmente. La calidad con el modelo publicado solo se conocerá después del despliegue.

## Documentación de equipo

`docs/sales-agent/README.md` concentra producto/rutas, responsabilidades LLM/backend, data y guías, diseño experimental, cambios reales de afinamiento, las 17 corridas y 119 conversaciones, avances/regresiones, consumo y referencias. El trabajo actual y el futuro quedan al final. Las figuras distinguen historia global de un seguimiento retrospectivo de los mismos tres IDs; no se inventa una corrida Repair 6 ni una mejora live aún no medida.

## Aplicar y medir

Copiar el ZIP desde la raíz respetando rutas. No hay eliminaciones.

```bash
git pull && git add . && git commit -m "Resolve explicit property switches with material requests and consolidate sales evaluation evidence" && git push
```

Después del despliegue:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --suite compact-battery \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --cases first_time_A move_up_B unknown_A \
  --max-calls 60 --max-turns 8 --output /tmp/sales-compact-repair-6
```

Se esperan tres diálogos aprobados y dos visitas. Estimación basada en Repair 5: USD 0,04–0,09; reserva orientativa 0,08–0,17, no un límite de gasto garantizado. El límite es de llamadas, no dólares. La simulación usa SQLite desechable y no envía mensajes ni crea citas de producción.

Copiar incluso si el resultado es FAIL:

```bash
docker cp bp_api_prod:/tmp/sales-compact-repair-6/synthetic-sales-results.zip ~/sales-compact-repair-6.zip
```

En PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-compact-repair-6.zip "$env:USERPROFILE\Downloads\sales-compact-repair-6.zip"
```
