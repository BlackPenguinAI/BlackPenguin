"""Shape and exclusivity for the multi-select questions already in the catalog.

No new field cardinalities are activated here. Mau's review remains separate.
"""
import re

EXCLUSIVE_OPTIONS = {
    "compliance_notes": ["Use standard Company compliance; no Project-specific notes"],
}
CONTROL_OPTIONS = {"not applicable", "no aplica", "n/a", "provide later", "configure later"}


def normalize_selection(field, value, options=(), *, validate_exclusivity=True):
    if value is None:
        return None
    if isinstance(value, str):
        text=value.strip()
        # Protect known labels containing separators before splitting the
        # existing human-readable chat transport. Never rewrite their label.
        labels=sorted((str(item) for item in options),key=len,reverse=True)
        protected={}
        for index,label in enumerate(labels):
            if ';' in label or ',' in label:
                marker=f"\x00option{index}\x00";protected[marker]=label
                text=re.sub(re.escape(label),lambda _:marker,text,flags=re.I)
        values=[]
        for part in re.split(r"[,;\n]",text):
            for marker,label in protected.items():part=part.replace(marker,label)
            if part.strip():values.append(part.strip())
    elif isinstance(value,list) and all(isinstance(item,str) for item in value):
        values=[item.strip() for item in value if item.strip()]
    else:
        raise ValueError("Choose one or more text options, or enter a list of text values.")
    canonical={str(item).casefold():str(item) for item in options}
    result=[];seen=set()
    for item in values:
        item=canonical.get(item.casefold(),item)
        if item.casefold() not in seen:result.append(item);seen.add(item.casefold())
    exclusive={item.casefold() for item in EXCLUSIVE_OPTIONS.get(field,[])} | CONTROL_OPTIONS
    if validate_exclusivity and len(result)>1 and any(item.casefold() in exclusive for item in result):
        raise ValueError("Choose 'not applicable', 'provide later', or the standard Company compliance option on its own, not with other choices.")
    if validate_exclusivity and len(result)==1 and result[0].casefold() in CONTROL_OPTIONS:
        raise ValueError("Use the dedicated not-applicable or configure-later action instead of saving it as profile information.")
    return result


def normalize_field_selection(field,value):
    from .onboarding_questions import QUESTION_CATALOG
    config=QUESTION_CATALOG.get(field,{})
    return normalize_selection(field,value,config.get('options',[])) if config.get('input_type')=='multi_select' else value


def selection_instruction():
    from .onboarding_questions import QUESTION_CATALOG
    fields=sorted(key for key,config in QUESTION_CATALOG.items() if config.get('input_type')=='multi_select')
    return ("MULTI-SELECTION CONTRACT: For these existing multi_select fields, value must be a JSON array of text values: "
            +", ".join(fields)+". Keep single-value fields single. Not-applicable and defer actions must stand alone; "
            "standard Company compliance cannot be combined with Project-specific restrictions. Cardinality proposals pending Mau review are not active. ")
