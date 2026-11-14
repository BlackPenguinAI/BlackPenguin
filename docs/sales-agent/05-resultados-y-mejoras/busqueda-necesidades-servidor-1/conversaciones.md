# Primera búsqueda por necesidades en el servidor

**Estado original: FAIL.** Modelo `openai/gpt-4o-mini`, configuración 8; commit `3e26f648364f18889d9240da575db0c5bb9b4ad1`. Ninguno de los 12 escenarios cumplió todos los checks. Un turno de los 14 los cumplió. Costo total registrado: USD 0.0336537 (29/29 llamadas con costo).

[Volver a la guía](../../README.md) · [JSON original](resultado.json) · [Diagnóstico](diagnostico.json)

## exact_two

**Lead:** I am looking for a 2 bedroom

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## house_two

**Lead:** Im looking for a 2 bedroom house

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## word_two

**Lead:** I'm looking for a two-bedroom home.

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## show_two

**Lead:** Please show me 2 bedroom homes.

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## need_three

**Lead:** I need a 3 bedroom home.

**Agente observado:**

> I need the property options to make this comparison.
> 
> Which property options would you like to compare?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, matches_explained, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## multiple_two

**Lead:** Do you have any 2 bedroom homes?

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Garden Home: bedrooms: 2.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## no_two

**Lead:** I am looking for a 2 bedroom home.

**Agente observado:**

> I need the property options to make this comparison.
> 
> Which property options would you like to compare?

**Checks fallidos:** needs_filter_executed, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## unknown_bedrooms

**Lead:** I am looking for a 2 bedroom home.

**Agente observado:**

> I need the property options to make this comparison.
> 
> Which property options would you like to compare?

**Checks fallidos:** needs_filter_executed, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## sold_out_four

**Lead:** I am looking for a 4 bedroom home.

**Agente observado:**

> 1. Summit Villa: bedrooms: 4.
> 
> 2. Ridge Townhome: bedrooms: 3.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

## unconfirmed_inventory

**Lead:** I am looking for a 2 bedroom home.

**Agente observado:**

> 1. Ridge Townhome: bedrooms:
> 
> 3.
> 
> 2. Valley Apartment: bedrooms: 2.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, uncertain_inventory_not_claimed_available, incomplete_catalog_not_exhaustive.

## change_need

**Lead:** I am looking for a 2 bedroom home.

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

**Lead:** Actually, I need a 1 bedroom home.

**Agente observado:**

> Here is a 1-bedroom option in this project:
> 
> Cedar Studio — 1 bedrooms, 52 m², from 210,000.00 USD.
> 
> The remaining catalog information is incomplete, so these may not be all the matching options.
> 
> Would you like to know more about Cedar Studio?

**Checks fallidos:** .

## no_premature_selection

**Lead:** I am looking for a 2 bedroom home.

**Agente observado:**

> 1. Cedar Loft: bedrooms: 2.
> 
> 2. Cedar Studio: bedrooms: 1.
> This compares approved records; unconfirmed values do not mean zero or unavailable.
> 
> Which option would you like to explore further?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, unmatched_names_not_presented, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

**Lead:** I am looking for a 1 bedroom home.

**Agente observado:**

> Could you clarify whether you want property details, materials, financing, or a visit?

**Checks fallidos:** needs_filter_executed, exact_matching_ids, matches_explained, bedroom_need_acknowledged, incomplete_catalog_not_exhaustive.

