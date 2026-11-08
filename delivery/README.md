# Continuidad de conversación y revisión de pausas

Base verificada en GitHub: d905c635d594c18c5e3dae830594a02fc0bb4dfb.
Este ZIP contiene únicamente archivos nuevos/modificados y la evidencia de validación.
Incluye las mejoras del último ZIP de flujo conectado; úsalo en su reemplazo.
También se puede aplicar sobre ese último ZIP, conservando estos archivos como versión final.
No apliques el ZIP anterior después de este, porque sobrescribiría las correcciones.

## Aplicación

1. Copia backend/, frontend/ y docs/ a sus mismas rutas del repositorio de esa base.
2. No hay archivos para eliminar, migraciones ni nuevas dependencias.
3. Compila y despliega backend y frontend juntos con el procedimiento habitual.
4. Conserva la configuración existente del runtime/cohort; este ZIP no la activa ni modifica.
5. Revisa las conversaciones ya pausadas desde Agent. No se reanudan ni se reenvían solas.

## Resultado

- Una interpretación inválida o ambigua no pausa la conversación. El agente puede pedir aclaración y atender el siguiente mensaje.
- Las notas de cumplimiento requieren revisión de la acción afectada, sin pausar toda la conversación solo por existir.
- Una etiqueta del modelo no basta para pausar o dar de baja al lead; se exige evidencia actual o confirmación explícita.
- Agent muestra motivo, regla, evidencia e historial; permite respuesta manual y reanudación.
- Marcar falso positivo exige una nota y registra quién/cuándo resolvió el caso. El mismo disparador revisado no vuelve a pausar de inmediato.
- Se conservan STOP, permisos, aprobaciones de acciones, control humano, cierre de cita y protección contra duplicados.

## Validación

Backend completo: 1485 aprobadas, 2 omitidas.
Revisión focal tras el último ajuste de nombre de revisor: 32 aprobadas.
Frontend: 37 aprobadas, incluida una prueba del template real de Angular con evidencia, nota obligatoria, reanudación e historial.
Build de producción: correcto, con avisos de tamaño de estilos ya existentes.
Comprobación de diff: correcta.
Los modelos y envíos están simulados. No hubo despliegue ni contacto con leads reales.
No se completó una inspección visual con capturas del navegador por restricciones de ejecución del entorno; sí se compilaron las plantillas y se probó su DOM.

Antes de cerrar los incidentes de la demo, hay que reproducir con nuevos mensajes los primeros turnos de Mau por SMS/WhatsApp y la consulta WhatsApp de Jorge, usando el modelo real y revisando /monitor.
La guía completa y las limitaciones de las notas de cumplimiento están en docs/sales-conversation-continuity-review.md.
