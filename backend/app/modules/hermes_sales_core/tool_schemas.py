"""Hermes v13.3.3 tool names/argument shapes, ported without direct demo implementations.

Descriptions are business guidance, NEVER permissions. Gateway authorization is separate.
P02 will replace demo-specific currencies/IDs using reviewed BP data contracts.
"""
from __future__ import annotations


def obj(fields: dict | None = None, *, required: list[str] | None = None, closed: bool = True) -> dict:
    result = {'type': 'object', 'properties': fields or {}}
    if required:
        result['required'] = required
    if closed:
        result['additionalProperties'] = False
    return result


def string(description: str = '', options: list[str] | None = None) -> dict:
    result: dict = {'type': 'string'}
    if description:
        result['description'] = description
    if options:
        result['enum'] = options
    return result


def integer(description: str = '') -> dict:
    result = {'type': 'integer'}
    if description:
        result['description'] = description
    return result


def number() -> dict:
    return {'type': 'number'}


def boolean() -> dict:
    return {'type': 'boolean'}


TOOLSET = 'blackpenguin_real_estate_demo'  # Keep the validated SDK toolset name in P01.

# Business-port tool contract (15 functions). Tool implementations come from the
# provided ToolPort, never from domain.py, an imported database or browser input.
SCHEMAS: dict[str, dict] = {
    'search_properties': {
        'description': 'Read published properties matching buyer filters. Use temporary scope for exploration (including new searches while a visit is pending). This read never changes primary preferences or the visit draft. Use update_search_preferences only for explicit lasting declarations. Keep useful successful search results if a later argument is rejected. Report catalog prices in explicit currency with full amounts; a buyer ceiling is a filter, not a listing price.',
        'parameters': obj({
            'scope': string('Default temporary for searches. Permanent only for an explicit lasting buyer declaration; search itself does not write preferences.', ['temporary','permanent']),
            'criteria': obj({
                'bedrooms': integer(),
                'bedrooms_any': {'type':'array','items':integer()},
                'max_price_usd': integer(), 'min_price_usd': integer(),
                'min_area_sqm': number(), 'max_area_sqm': number(),
                'min_bathrooms': number(), 'max_bathrooms': number(),
                'min_parking_spaces': integer(),
                'kitchen_layout': string(options=['open','closed','semi_open']),
                'private_backyard': boolean(),
                'relative_price_lt': integer(), 'relative_price_gt': integer(),
            }),
        }),
    },
    'track_property_interest': {
        'description': 'Track explicitly mentioned or explicitly preferred property. Discussed does not mean interested.',
        'parameters': obj({'unit_id': string('Published unit code'), 'status': string(options=['discussed','considering','interested'])},required=['unit_id','status']),
    },
    'get_project_overview': {
        'description': 'Read project, location, advantages and amenities.',
        'parameters': obj(),
    },
    'evaluate_properties_for_lead': {
        'description': 'Legacy demo tool for evaluation from saved profile. For new searches use search_properties.',
        'parameters': obj({
            'max_budget_usd': integer('Maximum USD price.'),
            'target_purchase_timeframe': string('Within 2 months or ASAP.'),
            'min_bedrooms': integer(),
            'preferred_property_type': string(options=['Apartment','House','Either']),
            'required_features': obj({
                'kitchen_layout': string(options=['open','closed','semi_open']),
                'private_backyard': boolean(), 'private_terrace':boolean(),
                'parking_spaces': number(), 'backyard_area_m2':number(),
            }),
        }),
    },
    'compare_properties': {
        'description': 'Read-only comparison of 2-3 named or recently offered properties. Never books a visit.',
        'parameters': obj({
            'unit_ids': {'type':'array','items':string(), 'minItems':2, 'maxItems':3},
        }),
    },
    'get_unit_details': {
        'description': 'Read verified price, size, location, amenities and availability for one selected unit. Never shares media.',
        'parameters': obj({'unit_id': string('Published unit code, optional when context unambiguous')}),
    },
    'list_unit_assets': {
        'description': 'Read-only discovery of approved media for one focused unit. No links are dispatched.',
        'parameters': obj({'unit_id': string()}),
    },
    'get_unit_media': {
        'description': 'Share only buyer-requested approved gallery/PDF URLs for focused property. Requires gateway authorization.',
        'parameters': obj({'unit_id': string()}),
    },
    'get_available_visit_slots': {
        'description': 'Search verified visit availability; broad periods return dates, exact dates return slots/proposals. No phantom availability.',
        'parameters': obj({
            'date_str': string('Optional YYYY-MM-DD, tomorrow, next week, this weekend, etc.'),
            'time_preference': string('Only if requested.', ['any','morning','afternoon','evening']),
        }),
    },
    'select_visit_time': {
        'description': 'Choose exact offered time from an active proposal. Selection is NOT booking.',
        'parameters': obj({'proposal_id':string(), 'date_str':string(), 'start_time':string()},
                          required=['proposal_id','date_str','start_time']),
    },
    'book_onsite_visit': {
        'description': 'Confirm booking only after explicit full-property/date/time consent; gateway owns transaction and advisor.',
        'parameters': obj({
            'first_name':string(), 'last_name':string(), 'email':string(), 'phone':string(),
            'unit_id':string(), 'proposal_id':string(), 'date_str':string(), 'start_time':string(),
        }, required=['first_name','last_name','email','phone','unit_id','proposal_id','date_str','start_time']),
    },
    'cancel_onsite_visit': {
        'description': 'Cancel existing confirmed visit only after explicit lead consent, via authorized gateway.',
        'parameters':obj({'meeting_id':string(), 'reason':string()},required=['meeting_id']),
    },
    'reschedule_onsite_visit': {
        'description': 'Reschedule an existing confirmed visit with fresh verified slot and lead consent.',
        'parameters':obj({
            'original_meeting_id':string(), 'first_name':string(), 'last_name':string(),
            'email':string(), 'phone':string(), 'date_str':string(),
            'start_time':string(), 'proposal_id':string(), 'unit_id':string(),
        },required=['original_meeting_id','first_name','last_name','email','phone','unit_id','date_str','start_time','proposal_id']),
    },
    'update_search_preferences': {
        'description': 'Update long-lived preferences only from current explicit buyer declaration; preserve provenance.',
        'parameters':obj({
            'budget_minimum_usd':integer(), 'budget_maximum_usd':integer(),
            'budget_target_usd':integer(), 'budget_exact_price_usd':integer(),
            'budget_mode':string(options=['cap','floor','range','target','fixed_funds','exact_price']),
            'bedrooms_min':integer(), 'bedrooms_max':integer(), 'bedrooms_preferred':integer(),
            'bedrooms_mode':string(options=['preferred','exact','minimum','maximum','range']),
        }),
    },
    'update_lead_profile': {
        'description': 'Record newly stated buyer facts only; validated gateway controls persistence.',
        'parameters':obj({
            'first_name':string(), 'last_name':string(), 'email':string(), 'phone':string(),
            'budget_usd':integer(), 'purchase_timeframe':string(),
            'property_type':string(options=['Apartment','House','Either']),
            'min_bedrooms':integer(), 'interest_unit_id':string(),
            'budget':string(), 'budget_minimum':integer(), 'budget_maximum':integer(),
            'budget_currency':string(), 'property_interest':string(), 'bedrooms':integer(),
            'bathrooms':string(), 'location_preference':string(), 'purchase_timeline':string(),
            'financing':string(), 'buyer_type':string(), 'motivation':string(),
            'decision_structure':string(), 'move_in_timing':string(),
            'visit_readiness':string(), 'needs':string(),
        }),
    },
}

# P01 cannot generate outbound messages, appointments, asset shares, or CRM writes.
# These methods are registered for SDK contract compatibility, but rejected
# before ToolPort invocation. P04 replaces these guards with BP authority.
P01_DENIED_TOOLS = frozenset({
    'get_unit_media', 'select_visit_time', 'book_onsite_visit',
    'cancel_onsite_visit', 'reschedule_onsite_visit',
    'update_search_preferences', 'update_lead_profile', 'track_property_interest',
})

assert len(SCHEMAS) == 15
