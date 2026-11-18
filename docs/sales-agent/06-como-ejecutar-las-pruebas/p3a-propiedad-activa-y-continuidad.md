# P3-A: propiedad activa y continuidad comercial

## Alcance

Este diferencial aborda solamente la selección de propiedad y la identidad
comercial. **No** cambia la búsqueda de horarios, su limitación a tres resultados,
la política humana ni las confirmaciones de reserva (P3-B y P3-C posteriores).

- La selección ordinal de un catálogo se interpreta antes del modelo solo si
  corresponde al **último catálogo efectivamente entregado**, con IDs válidos
  del proyecto y lista **idéntica** al orden visible en el mensaje.
- Si hay discordancia entre el orden registrado y el presentado, se solicita el
  nombre de la propiedad. Ningún ordinal selecciona por adivinanza.
- La interpretación determinista sigue siendo **solo lectura**. El planificador
  verifica las referencias y actualiza `selected_property_type_id`.
- Las solicitudes de materiales no pueden tomar silenciosamente un objetivo de
  otra propiedad cuando existe una selección activa.
- Las respuestas sobre una propiedad específica reciben un encabezado con su
  nombre aprobado si todavía no lo indican claramente.

## Pruebas sin proveedor externo

```bash
cd backend
python -m tools.sales_ai.p3a_property_selftest
```

No requiere OpenRouter, Telnyx ni mensajes reales. Se ejecuta en el mismo
entorno de test que el backend. También comprobar CI general y aceptación.

## Prueba controlada en WhatsApp/SMS

1. Crear un **lead de prueba autorizado** en una conversación independiente.
2. Pedir lista de propiedades. **Verificar** el orden tal como lo ve el lead.
3. Elegir `Second option`. Verificar que la propiedad elegida coincide con la
   segunda del mensaje efectivamente entregado (no con el orden actual de DB).
4. Pedir precio, folleto y galería. Verificar que cada respuesta identifica
   la propiedad seleccionada y que cada documento tiene cobertura autorizada.
5. Corregir explícitamente la propiedad, pedir otra vez materiales y observar
   que el siguiente turno usa la nueva selección.
6. Iniciar visita. La propiedad debe seguir seleccionada; **no** agendar sin
   una hora elegida, oferta vigente y confirmación inequívoca.

Rechazos esperados: catálogo sin lista numerada coherente, oferta caducada o
suplantada por otra pregunta, material sin propietario verificable, nombre no
aprobado en el proyecto. El sistema debe aclarar, nunca entregar el documento
potencialmente incorrecto.

## Limitaciones

No se ha ejecutado el CI completo en este entorno de construcción. Un diff que
aplica no reemplaza pruebas de integración SQL y de despacho real. No enviar
mensajes al lead existente hasta que los tests de backend y aceptación estén verdes.
