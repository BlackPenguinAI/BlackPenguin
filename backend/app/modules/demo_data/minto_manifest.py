"""Curated Minto demo data captured from official public sources.

Commercial values and inventory counts are deliberately labelled as generated
demo data.  They are not represented as current offers from Minto.
"""

from __future__ import annotations


DATASET_VERSION = "minto-demo-2026-08-v1"
COMPANY_URL = "https://www.minto.com/"

COMPANY_PROFILE = {
    "official_company_name": "The Minto Group",
    "preferred_display_name": "Minto",
    "official_corporate_website": {"exists": True, "url": COMPANY_URL},
    "headquarters": "Ottawa, Ontario, Canada",
    "primary_business_model": "Mixed model",
    "core_asset_classes": ["Single-family", "Condominiums", "Multifamily", "Office", "Retail"],
    "current_operating_footprint": "Canada and the United States",
    "approved_short_company_description": (
        "A leading homebuilder, developer, property manager, and investment manager "
        "with 70 years of operating history and more than 100,000 homes built."
    ),
    "corporate_value_proposition": (
        "Minto creates better places to live, work, and play through thoughtful homes, "
        "lasting relationships, innovation, and environmental accountability."
    ),
    "corporate_differentiators": (
        "Integrated development and management capabilities, seven decades of experience, "
        "more than 100,000 homes built, and a stated commitment to resilient communities."
    ),
    "year_established": "1955",
    "public_contact_phones": ["+1 877 751 2852"],
    "corporate_social_profiles": [
        "https://www.linkedin.com/company/minto-group-inc-",
        "https://www.instagram.com/mintogroupinc/",
    ],
    "secondary_business_activities": [
        "Apartment rentals", "Furnished suites", "Commercial leasing", "Property management", "Investment management",
    ],
    "mission": "Build better places to live, work, and play, one home and one relationship at a time.",
    "sustainability_principles": (
        "Build a resilient business, contribute positively to communities, and increase environmental responsibility."
    ),
    "completed_projects_count": "More than 100,000 homes built across the company's operating history.",
    "portfolio_summary": "New homes and condominiums, rental apartments, furnished suites, commercial space, and investment management.",
    "corporate_tagline": "More with Minto.",
    "company_history": "Minto was established in 1955 and reports 70 years of operation on its official website.",
}

COMPANY_FIELD_OVERRIDES = {
    "legal_company_name": {"status": "deferred", "applicable": True, "source_type": "demo_generated"},
    "dba": {"status": "not_applicable", "applicable": False, "source_type": "demo_generated"},
    "parent_company": {"status": "not_applicable", "applicable": False, "source_type": "demo_generated"},
    "additional_corporate_languages": {
        "value": ["English", "French"], "status": "confirmed", "applicable": True,
        "source_type": "official_company_website",
    },
    "corporate_compliance_information": {
        "value": ["Data privacy and communications consent", "Environmental, construction or building regulations"],
        "status": "confirmed", "applicable": True, "source_type": "demo_generated",
    },
}

COMPANY_IMAGE = {
    "asset": "company.jpg",
    "source_url": "https://media.minto.com/img/gallery/about_us/about_us/minto%20about%20us.jpg",
    "mime_type": "image/jpeg",
    "name": "Minto official company image",
}

PROJECTS = (
    {
        "template_version": "minto-wildflower-v1",
        "name": "Wildflower",
        "url": "https://www.minto.com/calgary/new-homes/Wildflower/main.html",
        "source_summary": (
            "Wildflower is a master-planned community in Airdrie offering single-family homes, duplex homes, and townhomes. "
            "Residents have access to the Hillside Hub and resort-style amenities."
        ),
        "profile": {
            "project_name": "Wildflower",
            "project_type": "Mixed residential community",
            "project_status": "Pre-sales",
            "short_description": "A master-planned Airdrie community with single-family homes, duplexes, townhomes, and resort-style amenities.",
            "exact_address": "1215 Fowler Road SW, Airdrie, Alberta",
            "city": "Airdrie, Alberta",
            "country": "Canada",
            "location_references": ["Upper west side of Airdrie", "Wildflower Sales Centre", "Hillside Hub"],
            "phases_and_towers": "Multiple low-rise residential phases; no towers.",
            "property_type_catalog": ["Single Family Homes", "Duplex Homes", "Townhomes"],
            "typologies": ["Single-family", "Duplex", "Townhouse"],
            "areas": {
                "Single Family Homes": "1,445-2,586 ft²",
                "Duplex Homes": "approximately 2,000 ft²",
                "Townhomes": "approximately 1,397 ft²",
            },
            "bedrooms_and_bathrooms": ["Duplex: 3 bed / 2.5 bath", "Townhome: 3-4 bedrooms"],
            "construction_details": "Low-rise homes in a variety of architectural designs, sizes, and product types.",
            "amenities": ["Outdoor pool", "Hot tub", "Open-air sports court", "Hillside Hub amenity building"],
            "parking_and_storage": "Attached garages for duplex homes and rear-drive garages for townhomes; details vary by floorplan.",
            "currency": "CAD",
            "starting_price": 429900,
            "payment_methods": "Demo assumption: reservation deposit and buyer-arranged financing; confirm current terms with Minto Sales.",
            "promotions": "No promotion is asserted in this demo dataset; confirm current incentives with Minto Sales.",
            "delivery_dates": "Quick-possession homes may be available; exact completion dates must be confirmed with Minto Sales.",
            "available_inventory": "Demo inventory is represented by the confirmed property-type catalog below.",
            "inventory_updated_at": "2026-08-18",
            "sales_authorization": "Simulation only. Do not send external messages or represent demo inventory as a binding offer.",
            "target_audience": "Homebuyers seeking single-family, duplex, or townhome living in Airdrie with community amenities and practical access to Calgary.",
            "value_proposition": "A variety of new-home formats paired with exclusive resort-style amenities and a connected master-planned community setting.",
            "key_differentiators": "Three home formats, Hillside Hub access, Airdrie's first outdoor pool, and quick-possession opportunities.",
            "qualification_rules": "Confirm preferred home type, bedrooms, budget range, purchase timeline, financing readiness, and interest in a presentation-centre appointment.",
            "sales_contacts": [{"name": "Wildflower Sales Centre", "phone": "+1 403 680 9215"}],
            "appointment_routing": "Round robin among active Sales users assigned to Wildflower; simulation does not contact external calendars.",
            "campaigns_defined": ["Wildflower New Home Interest"],
            "compliance_notes": "Prices, plans, specifications, dimensions, and availability must be confirmed by Minto Sales and may change without notice.",
        },
        "images": (
            {"key": "cover", "asset": "wildflower-cover.jpg", "mime_type": "image/jpeg", "primary": True,
             "source_url": "https://media.minto.com/img/ppages/301/Wildflower-Main-Section-Image.jpg"},
            {"key": "single-family", "asset": "wildflower-single-family.jpg", "mime_type": "image/jpeg",
             "source_url": "https://media.minto.com/img/ppages/301/Wildflower-in-Airdrie--SF-Homes-by-Minto-2511.jpg"},
            {"key": "duplex", "asset": "wildflower-duplex.jpg", "mime_type": "image/jpeg",
             "source_url": "https://media.minto.com/img/ppages/301/Wildflower-in-Airdrie--Duplex-Homes-by-Minto-2511.jpg"},
            {"key": "townhomes", "asset": "wildflower-townhomes.jpg", "mime_type": "image/jpeg",
             "source_url": "https://media.minto.com/img/ppages/301/Wildflower-in-Airdrie--Townhomes-Homes-by-Minto-2511.jpg"},
        ),
        "property_types": (
            {"name": "Single Family Homes", "code": "WF-SF", "description": "Detached homes on 32- to 38-foot lots.",
             "bedrooms": 3, "bathrooms": 2.5, "area_min": 1445, "area_max": 2586, "image_key": "single-family",
             "total_units": 8, "available_units": 3, "starting_price": 649900, "maximum_price": 899900},
            {"name": "Duplex Homes", "code": "WF-DX", "description": "Semi-detached homes with flexible layouts and attached garages.",
             "bedrooms": 3, "bathrooms": 2.5, "area_min": 1900, "area_max": 2100, "image_key": "duplex",
             "total_units": 6, "available_units": 2, "starting_price": 559900, "maximum_price": 689900},
            {"name": "Townhomes", "code": "WF-TH", "description": "Three- to four-bedroom townhomes with rear-drive garages.",
             "bedrooms": 3, "bathrooms": 2.5, "area_min": 1397, "area_max": 1397, "image_key": "townhomes",
             "total_units": 10, "available_units": 4, "starting_price": 429900, "maximum_price": 519900},
        ),
        "campaigns": ({"name": "Wildflower New Home Interest", "objective": "lead_generation"},),
    },
    {
        "template_version": "minto-east-hills-v1",
        "name": "East Hills Crossing",
        "url": "https://www.minto.com/calgary/new-homes/East-Hills-Crossing/main.html",
        "source_summary": (
            "East Hills Crossing is a residential community in Belvedere, Calgary, featuring contemporary townhomes and condos "
            "near East Hills Shopping Centre, rapid transit, Stoney Trail, and Highway 1."
        ),
        "profile": {
            "project_name": "East Hills Crossing",
            "project_type": "Mixed residential community",
            "project_status": "Pre-sales",
            "short_description": "Contemporary townhomes and condominiums in Belvedere with convenient access to shopping, transit, parks, and major roads.",
            "exact_address": "Stoney Trail and 17 Avenue SE, Calgary, Alberta",
            "city": "Calgary, Alberta",
            "country": "Canada",
            "location_references": ["Belvedere", "East Hills Shopping Centre", "Stoney Trail", "Highway 1", "Bus Rapid Transit"],
            "phases_and_towers": "Multiple low-rise residential buildings and townhome phases; no tower structure is advertised.",
            "property_type_catalog": ["Condominiums", "Rear Lane Townhomes", "Front Drive Townhomes"],
            "typologies": ["1 bedroom condo", "2 bedroom condo", "2 bedroom townhome", "3 bedroom townhome", "4 bedroom townhome"],
            "areas": "Floorplan-specific areas are available from Minto Sales; demo ranges are recorded in the property catalog.",
            "bedrooms_and_bathrooms": ["Condos: 1-2 bedrooms", "Townhomes: 2-4 bedrooms"],
            "construction_details": "Contemporary low-rise condominiums and townhomes with rear-lane or front-drive attached-garage configurations.",
            "amenities": ["Parks", "Pathways", "Nearby shopping and dining", "Nearby fitness facilities", "Rapid transit access"],
            "parking_and_storage": "Townhomes offer rear-lane or front-drive garage configurations; condominium details vary by floorplan.",
            "currency": "CAD",
            "starting_price": 329900,
            "payment_methods": "Demo assumption: reservation deposit and buyer-arranged financing; confirm current terms with Minto Sales.",
            "promotions": "A design-credit or basement-development offer appeared on the official page; eligibility and current terms require Sales confirmation.",
            "delivery_dates": "Quick-possession condominiums and townhomes may be available; confirm exact dates with Minto Sales.",
            "available_inventory": "Demo inventory is represented by the confirmed property-type catalog below.",
            "inventory_updated_at": "2026-08-18",
            "sales_authorization": "Simulation only. Do not send external messages or represent demo inventory as a binding offer.",
            "target_audience": "Homebuyers seeking contemporary condominiums or townhomes in southeast Calgary with access to shopping, transit, and major road connections.",
            "value_proposition": "Modern home choices in a walkable community close to East Hills Shopping Centre, rapid transit, parks, and regional road connections.",
            "key_differentiators": "Freehold townhomes without condo fees, condominium choices, quick possessions, and direct access to southeast Calgary amenities.",
            "qualification_rules": "Confirm condo or townhome preference, bedroom count, budget range, purchase timeline, financing readiness, and appointment availability.",
            "sales_contacts": [{"name": "East Hills Crossing Sales Centre", "phone": "+1 403 992 1261"}],
            "appointment_routing": "Round robin among active Sales users assigned to East Hills Crossing; simulation does not contact external calendars.",
            "campaigns_defined": ["East Hills Crossing New Home Interest"],
            "compliance_notes": "Prices, plans, specifications, dimensions, promotions, and availability must be confirmed by Minto Sales and may change without notice.",
        },
        "images": (
            {"key": "cover", "asset": "east-hills-cover.jpg", "mime_type": "image/jpeg", "primary": True,
             "source_url": "https://media.minto.com/slideshows/2733_mobile/EHC_Regional_Slideshow_Hero_Image%20Mobile%20600x400.jpg"},
            {"key": "sales-centre", "asset": "east-hills-sales-centre.png", "mime_type": "image/png",
             "source_url": "https://media.minto.com/dev/img/ppages/300/Overview%20Page%20Sales%20Office%20Image%20-%20612x612.png"},
        ),
        "property_types": (
            {"name": "Condominiums", "code": "EHC-CO", "description": "Contemporary one- and two-bedroom condominiums.",
             "bedrooms": 1, "bathrooms": 1, "area_min": 550, "area_max": 1050, "image_key": "cover",
             "total_units": 12, "available_units": 5, "starting_price": 329900, "maximum_price": 489900},
            {"name": "Rear Lane Townhomes", "code": "EHC-RL", "description": "Townhomes with rear-lane garage access and a pedestrian-focused streetscape.",
             "bedrooms": 3, "bathrooms": 2.5, "area_min": 1350, "area_max": 1800, "image_key": "sales-centre",
             "total_units": 8, "available_units": 3, "starting_price": 529900, "maximum_price": 669900},
            {"name": "Front Drive Townhomes", "code": "EHC-FD", "description": "Townhomes with attached garages accessed from the main street and flexible layouts.",
             "bedrooms": 3, "bathrooms": 2.5, "area_min": 1500, "area_max": 2100, "image_key": "sales-centre",
             "total_units": 8, "available_units": 2, "starting_price": 589900, "maximum_price": 749900},
        ),
        "campaigns": ({"name": "East Hills Crossing New Home Interest", "objective": "lead_generation"},),
    },
)


DEMO_GENERATED_PROJECT_FIELDS = {
    "starting_price", "payment_methods", "promotions", "delivery_dates", "available_inventory",
    "inventory_updated_at", "sales_authorization", "target_audience", "qualification_rules",
    "sales_contacts", "appointment_routing", "campaigns_defined", "compliance_notes",
}

PROJECT_NOT_APPLICABLE_FIELDS = {"meta_connection_verified"}
