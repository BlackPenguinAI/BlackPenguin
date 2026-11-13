# Búsqueda por necesidades · experimento local

**Origen: local, proveedor del modelo simulado (`test/offline`).** El core, el catálogo aprobado, la persistencia y los validadores son los del producto. No es evidencia de calidad del modelo publicado ni una corrida del servidor. Costo OpenRouter: USD 0.00.

12 casos, 14 turnos. Todos cumplieron los checks específicos. No hay aprobación integral del diálogo.

[Volver a la guía](../../README.md) · [Evidencia JSON](resultado.json)

## exact_two

**Lead:** I am looking for a 2 bedroom

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## house_two

**Lead:** Im looking for a 2 bedroom house

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## word_two

**Lead:** I'm looking for a two-bedroom home.

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## show_two

**Lead:** Please show me 2 bedroom homes.

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## need_three

**Lead:** I need a 3 bedroom home.

**Agente:**

> Here is a 3-bedroom option in this project:
> 
> Ridge Townhome — 3 bedrooms, 165 m², from 460,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Ridge Townhome?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## multiple_two

**Lead:** Do you have any 2 bedroom homes?

**Agente:**

> Here are the 2-bedroom options in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> Cedar Garden Home — 2 bedrooms, 90 m², from 285,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Which of these options would you like to explore?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## no_two

**Lead:** I am looking for a 2 bedroom home.

**Agente:**

> I do not have a confirmed 2-bedroom option to show you in this project. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 2 bedrooms essential, or would you consider another bedroom count?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## unknown_bedrooms

**Lead:** I am looking for a 2 bedroom home.

**Agente:**

> I do not have a confirmed 2-bedroom option to show you in this project. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 2 bedrooms essential, or would you consider another bedroom count?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## sold_out_four

**Lead:** I am looking for a 4 bedroom home.

**Agente:**

> The 4-bedroom options listed here have a last confirmed quantity of zero. Some catalog or bedroom details are missing, so I cannot rule out other matching options.
> 
> Are 4 bedrooms essential, or would you consider another bedroom count?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## unconfirmed_inventory

**Lead:** I am looking for a 2 bedroom home.

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Valley Apartment — 2 bedrooms, 95 m².
> 
> Current availability for Valley Apartment still needs confirmation.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Valley Apartment?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## change_need

**Lead:** I am looking for a 2 bedroom home.

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

**Lead:** Actually, I need a 1 bedroom home.

**Agente:**

> Here is a 1-bedroom option in this project:
> 
> Cedar Studio — 1 bedrooms, 52 m², from 210,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Studio?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

## no_premature_selection

**Lead:** I am looking for a 2 bedroom home.

**Agente:**

> Here is a 2-bedroom option in this project:
> 
> Cedar Loft — 2 bedrooms, 110 m², from 325,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Loft?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

**Lead:** I am looking for a 1 bedroom home.

**Agente:**

> Here is a 1-bedroom option in this project:
> 
> Cedar Studio — 1 bedrooms, 52 m², from 210,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Studio?

**Resultado:** PASS en los checks de búsqueda; calidad integral no evaluada.

