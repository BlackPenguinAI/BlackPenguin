"""Canonical intent contract shared by runtime validation and prompt publication."""
import math
from .default_prompt import SALES_INTENT_KEYS

CONTRACT_VERSION = "sales-intents-v1"

def normalize_intent(value):
    issues = []
    primary = value.get("primary_intent", value.get("intent"))
    if primary not in SALES_INTENT_KEYS:
        primary = "unclear"; issues.append("unknown_primary_intent")
    confidence = value.get("intent_confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        confidence = 0.0; issues.append("missing_or_invalid_confidence")
    secondary = value.get("secondary_intents", [])
    if not isinstance(secondary, list):
        secondary = []; issues.append("invalid_secondary_intents")
    if any(not isinstance(i, str) or i not in SALES_INTENT_KEYS for i in secondary):
        issues.append("unknown_secondary_intent")
    secondary = list(dict.fromkeys(i for i in secondary if isinstance(i,str) and i in SALES_INTENT_KEYS and i != primary))
    entities = value.get("intent_entities", {})
    if not isinstance(entities, dict):
        entities = {}; issues.append("invalid_entities")
    clean = {}
    for key in ("requested_materials","property_reference","requested_date"):
        item = entities.get(key)
        if key == "requested_materials":
            valid = isinstance(item,list) and len(item)<=20 and all(isinstance(v,str) and len(v)<=180 for v in item)
        else:
            valid = item is None or isinstance(item,str) and len(item)<=300
        if valid: clean[key] = item
        elif item is not None: issues.append("invalid_entity:"+key)
    flag = value.get("requires_clarification", False)
    if not isinstance(flag,bool): issues.append("invalid_clarification_flag")
    return {"primary_intent":primary,"intent":primary,"intent_confidence":float(confidence),
        "secondary_intents":secondary,"intent_entities":clean,
        "requires_clarification":flag is True or bool(issues) or primary == "unclear",
        "intent_contract_issues":issues}

CONTRACT_INSTRUCTION = (
    "INTENT CONTRACT sales-intents-v1 overrides legacy free-form intent labels. "
    "Return primary_intent as a canonical key, secondary_intents as distinct canonical keys, "
    "intent_confidence as a finite JSON number from 0 to 1, intent_entities as an object with "
    "requested_materials (string array), property_reference and requested_date (strings or null), "
    "and requires_clarification as a boolean. Never fabricate maximum confidence. "
    "Photos, PDFs and virtual tours are not in-person appointments. For mixed requests return all applicable intents. "
    "If ambiguous use unclear and ask one specific clarification; do not book anything."
)

