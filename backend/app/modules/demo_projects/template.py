from __future__ import annotations

from datetime import datetime, timezone

from app.modules.projects.completion import FIELDS


TEMPLATE_VERSION = "v1"

PROFILE_DATA = {
    "project_name": "Demo",
    "project_type": "Residential development",
    "project_status": "Under construction",
    "short_description": "A synthetic residential Project created to demonstrate a completed Black Penguin workspace.",
    "project_cover": "Demo placeholder artwork",
    "exact_address": "100 Demo Avenue (fictional)",
    "city": "Miami",
    "country": "United States",
    "location_references": ["Fictional waterfront district", "Demo transit station"],
    "phases_and_towers": "One residential tower used only for demonstration.",
    "typologies": ["1BR", "2BR", "3BR"],
    "property_type_catalog": ["1BR", "2BR", "3BR"],
    "areas": {"1BR": "62-70 m2", "2BR": "88-105 m2", "3BR": "128-145 m2"},
    "bedrooms_and_bathrooms": ["1 bed / 1 bath", "2 bed / 2 bath", "3 bed / 3 bath"],
    "construction_details": "Synthetic contemporary concrete-and-glass tower.",
    "amenities": ["Pool", "Fitness center", "Coworking lounge", "Rooftop terrace"],
    "parking_and_storage": "One parking space per unit; storage subject to availability.",
    "currency": "USD",
    "starting_price": 420000,
    "payment_methods": "20% reservation and down payment; balance at closing.",
    "promotions": "No active promotion.",
    "delivery_dates": "Q4 2028 (synthetic)",
    "available_inventory": "See the six synthetic units in inventory.",
    "inventory_updated_at": datetime.now(timezone.utc).isoformat(),
    "sales_authorization": "Demo only. External contact is prohibited.",
    "target_audience": "International buyers and urban professionals (synthetic persona).",
    "value_proposition": "Flexible layouts with shared work and wellness amenities.",
    "key_differentiators": ["Demo-ready inventory", "Illustrative routing", "Complete onboarding"],
    "qualification_rules": "Ask budget, preferred typology, purchase timeframe and financing needs.",
    "sales_contacts": [{"name": "Demo Sales Advisor", "email": "demo@example.invalid"}],
    "appointment_routing": "Demo routing only; do not create external meetings.",
    "campaigns_defined": ["Demo Awareness", "Demo High Intent"],
    "meta_connection_verified": "Not applicable for a Demo Project.",
    "compliance_notes": "All people, addresses, prices and inventory in this Project are synthetic.",
}

FIELD_STATES = {
    field.key: {"status": "confirmed", "applicable": True}
    for field in FIELDS
}
FIELD_STATES["project_cover"] = {"status": "not_applicable", "applicable": False}

UNITS = (
    ("D-101", "1BR", 62, 1, 1, 420000, "available"),
    ("D-102", "1BR", 70, 1, 1, 455000, "reserved"),
    ("D-201", "2BR", 88, 2, 2, 610000, "available"),
    ("D-202", "2BR", 105, 2, 2, 695000, "available"),
    ("D-301", "3BR", 128, 3, 3, 835000, "available"),
    ("D-302", "3BR", 145, 3, 3, 920000, "sold"),
)

CAMPAIGNS = (
    ("Demo Awareness", "awareness", "paused"),
    ("Demo High Intent", "lead_generation", "paused"),
)

LEADS = (
    ("Sofia Ramirez", "+1555000101", "sofia@example.invalid", "new", 0.42),
    ("Daniel Chen", "+1555000102", "daniel@example.invalid", "contacted", 0.66),
    ("Elena Rodriguez", "+1555000103", "elena@example.invalid", "qualified", 0.82),
    ("Marcus Johnson", "+1555000104", "marcus@example.invalid", "appointment_set", 0.91),
)
