# Grupo L — Despliegue verificable y reversión

Preparado, **no ejecutado**. El workflow de producción existente se activa al hacer push a main.
Aplicar/revisar los diferenciales en una rama de revisión; no integrar en main como forma de probar
un paquete aún bloqueado. Este trabajo no modifica ese workflow ni hace push o merge.

## Antes del corte

1. Cerrar los pendientes de K y la aceptación real autorizada. Elegir un SHA inmutable; guardar
   aprobaciones y los digests de las imágenes API/worker/frontend compatibles. No usar `latest`
   como única referencia de reversión ni mezclar componentes construidos desde distintas revisiones.
2. Revisar configuración publicada/draft, modelo, allowlists, roles, capacidades de proyecto,
   consentimiento y servicios del entorno. No ejecutar `init_db` para “actualizar prompts” ni
   importar el fixture histórico de K como pack vigente.
3. Respaldar DB, archivos/materiales y secretos necesarios para leerlos en su ubicación segura.
   Verificar restauración en un destino aislado. Guardar `release_audit` de API y worker, todos los
   Projects origen/destino de cambios y todas las páginas de propuestas/esperas del ámbito.
4. Comparar DB con `group-l-migration-inventory.json`. No hay migración nueva L; el head esperado
   sigue `20261108_sales_moderation`. Si faltan migraciones previas, ejecutarlas sólo dentro del
   procedimiento autorizado y antes de arrancar escritores que dependan de ellas. No hacer downgrade.
5. Definir una pausa de mantenimiento que evite dos versiones actuando sobre los mismos trabajos.
   Confirmar cómo se retienen/reintentan webhooks durante el corte; si no se puede preservar ingreso
   y colas, no continuar el corte y preferir corregir hacia delante. No inventar un modo de buffering
   que la aplicación no tenga. Bajar sólo una bandera puede reenviar al grafo legado: no es una
   garantía de detener mensajes, reservas o confirmaciones de propuestas anteriores.

## Comprobación de la versión instalada

La entrega no demuestra que algo esté instalado. Después de un despliegue autorizado comprobar:

| Evidencia | Verificación |
|---|---|
| Imágenes inmutables | Labels `org.opencontainers.image.revision`, IDs/digests y SHA seleccionado de los tres contenedores. |
| API | `/api/v1/health/version` coincide en commit; `/api/v1/health/ready` indica esquema compatible. |
| Worker | Audit ejecutado dentro del worker, commit/configuración coincidentes, proceso sano y progreso de un trabajo real del ensayo. El healthcheck de onboarding por sí solo no prueba Sales. |
| Frontend | `/release.json` sin caché: commit conocido y digest de assets. Comprobar la UI y las rutas desde la versión instalada. |
| Estado comercial | Configuración publicada identificada por versión/hash, flags, ámbito del lead de prueba y permisos vigentes. |
| Efectos | Recibos terminales/observación en el teléfono, Meeting, Calendar y avisos realmente comprobados. |

La CLI de audit y el JSON frontend no verifican procedencia criptográfica de una imagen por sí
solos. El operador compara esos datos con los artifacts de CI y sus digests. La compilación local
con `production,offline-ci` mantiene scripts/estilos optimizados y no incrusta fuentes externas;
no equivale a haber construido la imagen Docker ni a una aceptación visual con todas las fuentes.

## Reversión conservando verdad y evidencia

El retorno de referencia para cambios exclusivos de L es la imagen **K compatible**, de la base
`41c4abee4e47e02d2c77d57ca8a6961844a6ebb8`, si existe una imagen verificada de esa revisión en el
entorno. No se afirma que esa imagen esté desplegada o construida aquí. K ya comprende los campos
y tablas de J; no volver a un lector anterior a esas migraciones sin una evaluación independiente.
L no cambia el contrato de propuestas ni añade tablas.

Detener/coordenar escritores e ingreso según el plan autorizado; tomar un inventario estable.
Restaurar API, worker y frontend compatibles de forma coherente, conservar el esquema aditivo,
archivos, claves de idempotencia, revisiones y recibos. Conciliar efectos externos antes de reanudar.

| Estado al revertir | Tratamiento que conserva la verdad |
|---|---|
| Propuesta aún sin confirmar | Mantener JSON/revisión/hash/TTL y mensaje de origen. Un lector compatible puede dejarla caducar o revisarla por el flujo existente. Si no hay lector compatible, mantener el turno bajo control humano; no convertir un “Yes” antiguo en una autorización nueva. |
| Primera reserva ya guardada, Calendar pendiente | Conservar Meeting y operación. Reconciliar por el ID determinista guardado; reintentar sólo su efecto autorizado, sin reservar otra vez. |
| Reemplazo guardado | La nueva reserva sigue siendo la verdad. No reactivar la original cancelada ni borrar el recibo. Verificar creación del nuevo evento y retiro del anterior respetando los bindings persistidos. |
| Cancelación guardada | No restaurar la cita por revertir código. Conservar operación y cleanup de eventos/avisos; comprobar el efecto real antes de un reintento. |
| Espera o aviso preparado | Conservar preferencias, vencimiento, lease/token y payload preparado. Reconciliar resultado incierto antes de contactar de nuevo; no reiniciar esperas cerradas o avisos ya aceptados. |
| Recibo enviado/entregado/leído | No eliminar ni rebajar evidencia. Conservar IDs del proveedor y partes del grupo; restaurar una imagen no significa que un mensaje anterior haya desaparecido del teléfono. |
| Pausa, revisión o baja | Conservar motivo, decisión y consentimiento. Reanudar sólo lo autorizado; no levantar control humano previo ni una baja al restaurar el servicio. |

No borrar tablas, eventos, archivos ni propuestas con SQL manual; no marcar todo como completado
ni restaurar una copia antigua de DB sobre escrituras nuevas sin reconciliación. No rotar las claves
de cifrado que permiten leer los archivos/tokens existentes como efecto colateral del rollback.

Después del retorno, repetir auditorías y comparar recuentos/IDs del ámbito, versiones, colas,
propuestas, citas y efectos externos; revisar un recorrido del contacto autorizado antes de retirar
la pausa. Registrar cualquier divergencia y mantener bloqueado lo que no se haya conciliado.
