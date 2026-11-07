# Onboarding: segundo diferencial

## Base y aplicación

Base exacta: `856a36b6b817775e0cdc7a0955bfaa1a62ce0124` (main; incluye el primer diferencial que subiste).
Este ZIP es incremental: NO sustituye la primera entrega ni corresponde a bf6623f.
Copiar backend/, frontend/ y docs/ sobre la raíz del repositorio, sin borrar otros archivos.
delivery/ contiene instrucciones, commit, manifiesto SHA-256 y logs locales.
No requiere migraciones ni nuevas dependencias. No se hicieron commits, push, despliegues ni cambios en producción.

## Implementado en este bloque

### Selecciones aplazadas

- Provide later guarda las selecciones y detalles incompletos en ui_deferrals, nunca en datos aprobados.
- El servidor verifica Company/Project, pregunta activa, campo y formato de la selección.
- Retomar restaura exactamente los valores, incluidos textos con puntuación, sin enviarlos como una respuesta automáticamente.
- La recarga por API se prueba en Project, además de persistencia de Company.
- Se puede retomar un campo ya confirmado sin degradar el perfil publicado. La aprobación de la revisión permanece separada.
- Un fallo de guardado deja las selecciones visibles para reintentar. Las peticiones nuevas tienen un tiempo límite para evitar bloqueos indefinidos.

### Compliance específico

- Las nuevas preguntas incluyen un contrato detail_options. Cada categoría seleccionada requiere instrucciones concretas antes de confirmar.
- El usuario puede guardar un borrador incompleto y completarlo después.
- Usar las reglas estándar de Company no requiere inventar instrucciones adicionales y sigue siendo una opción exclusiva.
- Los mensajes históricos sin detail_options conservan su contrato anterior. No se reescriben respuestas antiguas.
- Las instrucciones se almacenan como valores de texto explícitos dentro de la lista existente; no se generan políticas legales automáticamente.
- No se ha auditado ni cambiado todavía cómo el agente de ventas consume estas instrucciones.

### Fechas de entrega con alcance explícito

- Nuevo formulario para Project completo, fase/edificio, tipo de propiedad o unidad individual.
- El usuario indica la referencia y elige mes/año o día exacto. Un mes no inventa un día.
- Validación de fechas imposibles, referencias vacías, duplicados de alcance y pregunta obsoleta.
- Nuevos accesos directos Delivery dates y Parking / storage.
- Se conserva almacenamiento textual legible en el campo delivery_dates existente y su versión aprobada, sin migraciones.
- Las referencias son nombres/códigos declarados, NO claves foráneas a fases/unidades. No constituyen un calendario relacional ni actualizan otros registros automáticamente.
- Fechas antiguas como Dec 2026 permanecen visibles y no reciben un alcance inventado. Al editarlas se exige escoger el alcance.

### Parking y almacenamiento

- Formulario con aplicación, garaje, plazas asignadas, visitantes, almacenamiento y condiciones de inclusión/precio.
- Campos desconocidos quedan en blanco: blanco no significa cero, ausencia ni no aplicable.
- Not applicable y Complete later son decisiones separadas.
- Guardado determinista con historial, comprobación de permisos, idempotencia y borrador publicado preservado. Un reintento del mismo formulario tras timeout reutiliza la identidad de la petición.

### Contactos e identidad de Company

- Permite continuar usando canales ya confirmados, sin exigir un nuevo correo comercial.
- No omite valores nuevos que aún requieren revisión ni borra canales existentes.
- Corrige la validación de valores nulos cuando la decisión es missing/deferred/not_applicable; confirmar un correo o teléfono sigue requiriendo un valor válido.
- Desactiva el estado de reanudación de enriquecimiento al continuar, evitando otro bucle.
- JSON-LD name se propone como preferred_display_name; legalName respalda official_company_name.
- Varias oficinas sin identificación de sede no se convierten arbitrariamente en headquarters.
- No ofrece copiar el nombre comercial como DBA cuando es idéntico al nombre legal.
- Las propuestas muestran su fuente y distinguen sugerencia de valor revisado.

## Pruebas

Resultados locales: backend **1438 passed, 2 skipped**; frontend **196 passed** (20 archivos); build de producción correcto.

Las corridas locales están en delivery/backend-tests.log, frontend-tests.log y frontend-build.log.
Backend: suite completa de pytest, incluyendo las nuevas pruebas de guardado, recuperación, permisos y precisión de fechas.
Frontend: `npm run test:onboarding`, con la configuración de regresión incorporada en el primer bloque.
Build: `npm run build`.
No se afirma que el comando genérico npm test esté verde: los tests scaffold/legacy excluidos en la primera entrega siguen pendientes.
Persisten las advertencias de tamaño de estilos de agent.scss y sales.scss.
No hubo pruebas con proveedores reales ni validación visual mediante navegador.

## Pendientes del plan general

1. Participación Sales de usuarios con otros roles: no se ampliaron permisos. Requiere revisar elegibilidad, routing, agenda y autorización por Project de extremo a extremo; habilitar solo el selector sería inconsistente e inseguro.
2. Vinculación relacional de fechas a entidades reales, si se desea automatización sobre fases/tipos/unidades. Esta entrega captura alcance explícito y precisión en el perfil existente.
3. Validación manual de Meta real: éxito, cancelación, error, expiración y regreso al Project correcto.
4. QA visual de todas las tarjetas de fuentes, logos y materiales en laptop/móvil.
5. Verificación de cobertura de extracción con páginas/PDF reales; no se promete extracción completa por cambiar instrucciones.
6. Diálogo del Sales AI y consumo efectivo de target/qualification/compliance, expresamente fuera de este bloque.
7. Corrección humana de los datos de prueba de Ashville Park: 3734 m² frente a 3734 sq ft, dirección concatenada y alcance/origen de cantidades. No se reescribió producción.

## Aceptación manual sugerida

- Seleccionar dos opciones de compliance, escribir parcialmente una regla, aplazar, recargar, retomar y comprobar ambas opciones/texto.
- Completar las instrucciones, guardar y revisar que se pide aprobación separada antes de publicar.
- Registrar una entrega mensual de fase y otra exacta de unidad; reabrir y comprobar precisión y referencias.
- Probar un duplicado de alcance y una fecha imposible: deben rechazarse sin perder el formulario.
- Confirmar parking, aplazarlo con datos y retomar; comprobar Not applicable por separado.
- Company con teléfono confirmado y correo vacío: continuar sin inventar correo; Company sin canales: no debe saltar esa comprobación.
- Reabrir una revisión ya aprobada: conservar versión publicada y exigir confirmación explícita de cambios.

