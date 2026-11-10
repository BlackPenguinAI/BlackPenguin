"""Exact-source quotation choices for the existing single provider repair."""
import copy
import json
import re


def evidence_choices(text, raw=None):
    choices=[]
    def add(value):
        if isinstance(value,str) and value.strip() and value in text and len(value)<=2000 and value not in choices:
            choices.append(value)
    add(text)
    for match in re.finditer(r'[^.!?;\n]+[.!?;]?',text):add(match.group().strip())
    for match in re.finditer(r'[^,;.!?\n]+[,;.!?]?',text):add(match.group().strip())
    try:
        data=json.loads(raw) if isinstance(raw,str) else {}
        for name in ('requests','preferences'):
            for item in data.get(name,[]):add(item.get('evidence'))
    except (ValueError,TypeError,AttributeError):pass
    return choices[:16]


def constrained_repair_schema(schema, text, raw=None):
    result=copy.deepcopy(schema);choices=evidence_choices(text,raw)
    # Shared definitions keep the extra schema small. Other fields retain their
    # normal schema and all fields still pass the unchanged exact-source parser.
    for name in ('Request','Preference'):
        evidence=result.get('$defs',{}).get(name,{}).get('properties',{}).get('evidence')
        if evidence is not None and choices:evidence['enum']=choices
    return result
