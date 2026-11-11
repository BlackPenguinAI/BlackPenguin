# Repair 5: alcance de propiedad, información sin visita y documentación

Base desplegada: `ffef47639bc01fdf776a8ee6b0fdbc17863b2d40`.

## Cambios de comportamiento

La corrida Repair 4 completó las dos visitas esperadas y entregó PDF/galería. Quedó un fallo de composición en `move_up_B`: catálogo amplio pese a resolver Cedar Studio, directiva de visita sobre “Please show me Cedar Studio”, `catalog_order` y timeout del segundo intento.

El planner ahora conserva property_id/unit_id en solicitudes de catálogo ligadas a una referencia. Un catálogo general sin referencia mantiene su alcance anterior. La normalización elimina la directiva de visita cuando su evidencia es únicamente una instrucción literal de mostrar/informar sobre una propiedad nombrada exactamente. No convierte consultas en consentimiento para agendar.

El compositor restaura el orden del backend cuando el único defecto es una permutación de evidencias ya autorizadas y completas. Mantiene wordings, continuación y número de elementos por párrafo; no agrega ni elimina hechos. Si faltan evidencias, hay referencias desconocidas, continuación inválida o agrupación inconsistente, la validación sigue rechazando el plan. La traza registra selección original, normalización y selección ejecutada. Esto evita otra llamada por un defecto de presentación reparable; no garantiza ausencia de timeouts del proveedor.

La evaluación añade controles de alcance inicial de Cedar Studio y ausencia de consentimiento de visita en esa consulta. No cambia modelo, dependencias, migraciones, SMS/WhatsApp ni permisos.

## Documentación incluida

[Guía para producto, operaciones y desarrollo](sales-agent/README.md), enlazada al principio del README principal. Incluye una empresa, tres proyectos, seis propiedades, ocho perfiles y cinco roles de vendedor por escenario, 16 escenarios, 98 conversaciones de 14 corridas, revisiones humanas separadas de resultados automáticos y tres gráficas NumPy/Matplotlib. Los JSON históricos son campos seleccionados de evidencia sintética del servidor; no incluyen credenciales ni prompts completos. También se incluyen herramientas de regeneración de snapshots y gráficas.

No se añade un resultado live de Repair 5: queda pendiente después del despliegue. Las figuras conservan regresiones, separan conjuntos y señalan costos incompletos.

## Validación

Regresión completa: 3.003 pruebas aprobadas, siete omitidas, cero fallos, 127 módulos cubiertos exactamente una vez. Aceptación técnica: 63 PASS, cero FAIL y una prueba live pendiente. Después de añadir los checks del evaluador se aprobaron 123 pruebas relevantes; se solapan con la regresión y no se suman a su total.

Se ejecutó el exportador en SQLite desechable y se verificaron JSON, enlaces relativos, índices únicos y ausencia de campos de credenciales/prompts. Se generaron e inspeccionaron las gráficas. No se hicieron llamadas de inferencia pagadas localmente.

## Despliegue y repetición

Copiar los archivos respetando las rutas; no hay eliminaciones ni migraciones.

```bash
git pull && git add . && git commit -m "Fix scoped sales catalog responses and document the synthetic evaluation laboratory" && git push
```

[Comandos SSH y PowerShell para repetir los tres casos](sales-agent/06-como-ejecutar-las-pruebas/README.md). Se esperan dos visitas y tres conversaciones sin fallos, con la misma configuración publicada. Copiar el ZIP aun si devuelve FAIL.
