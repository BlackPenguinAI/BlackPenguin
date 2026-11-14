# Reparación · replay local de interpretaciones del servidor

**12/12 escenarios y 14/14 turnos cumplieron sus checks de búsqueda al reproducir interpretaciones registradas.** El proveedor es simulado. No es una nueva corrida de GPT ni una evaluación integral del diálogo. Costo OpenRouter: USD 0.00.

[Volver a la guía](../../README.md) · [Resultado JSON](resultado.json)

## exact_two

**Lead:** I am looking for a 2 bedroom

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## house_two

**Lead:** Im looking for a 2 bedroom house

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## word_two

**Lead:** I'm looking for a two-bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## show_two

**Lead:** Please show me 2 bedroom homes.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## need_three

**Lead:** I need a 3 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 3-bedroom option in this project:
> 
> Ridge Townhome — 3 bedrooms, 165 m², from 460,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Ridge Townhome?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## multiple_two

**Lead:** Do you have any 2 bedroom homes?

**Respuesta del core corregido, con proveedor simulado:**

> Here are the 2-bedroom options in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> Cedar Garden Home — 2 bedrooms, 90 m², from 285,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Which of these options would you like to explore?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## no_two

**Lead:** I am looking for a 2 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> I do not have a confirmed 2-bedroom option to show you in this project. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 2 bedrooms essential, or would you consider another bedroom count?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## unknown_bedrooms

**Lead:** I am looking for a 2 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> I do not have a confirmed 2-bedroom option to show you in this project. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 2 bedrooms essential, or would you consider another bedroom count?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## sold_out_four

**Lead:** I am looking for a 4 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> The 4-bedroom options listed here have a last confirmed quantity of zero. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 4 bedrooms essential, or would you consider another bedroom count?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## unconfirmed_inventory

**Lead:** I am looking for a 2 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Valley Apartment — 2 bedrooms, 95 m².
> 
> Current availability for Valley Apartment still needs confirmation.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Valley Apartment?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## change_need

**Lead:** I am looking for a 2 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

**Lead:** Actually, I need a 1 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 1-bedroom option in this project:
> 
> Cedar Studio — 1 bedroom, 52 m², from 210,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Studio?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

## no_premature_selection

**Lead:** I am looking for a 2 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Confianza registrada:** 1.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 1.0, 'effect_authorization': False}. No autoriza efectos.

**Lead:** I am looking for a 1 bedroom home.

**Respuesta del core corregido, con proveedor simulado:**

> Here is a 1-bedroom option in this project:
> 
> Cedar Studio — 1 bedroom, 52 m², from 210,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Studio?

**Confianza registrada:** 0.0.

**Autorización de lectura literal:** {'version': 'sales-needs-search/1.1', 'basis': 'validated_current_literal_catalog_request', 'model_confidence': 0.0, 'effect_authorization': False}. No autoriza efectos.

