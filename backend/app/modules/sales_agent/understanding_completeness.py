"""Exact scoped subjects and bounded completeness checks, never write consent."""
import re
from .understanding_contract import Understanding,BUYER_SEGMENTS

SUBJECT_TOPICS={'catalog','property_details','inventory','pricing','materials','appointment','location','delivery','amenities'}
REPORTED=re.compile(r"\b(?:friend|said|says|told|quoted|example|suppose|if|not|don't|don.t|without)\b",re.I)
PURPOSE=re.compile(r"\bI\s+(?:am\s+)?(?:buying my first (?:home|house|property)|(?:want|need) to (?:move[^.!?]{0,90}(?:larger|bigger) (?:home|house)|downsize|diversify[^.!?]{0,70}(?:portfolio|real estate))|(?:am )?relocating|(?:am )?investing[^.!?]{0,90}(?:appreciation|resale)|(?:am )?buying[^.!?]{0,100}rental income)\b",re.I)
RETURNS=re.compile(r'\b(?:rental yield|annual (?:rental )?yield|occupancy|return on investment|ROI|rental returns?)\b',re.I)


def returns_question(text):
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    return bool(RETURNS.search(own) and re.search(r'\?|\b(?:what|how|can|could|tell|show|give)\b',own,re.I))


def scoped_subjects(value,text,commercial):
    """Attach an exact current-message catalog name to an existing request.

    No fuzzy matching, new requests, preferences, comparisons, slot references,
    appointment directives or consent. Ambiguity and explicit model links survive.
    """
    from app.modules.governance.services import request_attribution
    own=request_attribution(text)['current_text']
    # A named individual unit cannot be collapsed into its parent typology.
    for row in commercial.get('inventory',[]):
        code=row.get('unit_code')
        if isinstance(code,str) and code and re.search(r'(?<!\w)'+re.escape(code)+r'(?!\w)',own,re.I):return value,[]
    names=[r.get('property_type') for r in commercial.get('property_types',[])]
    matches=[]
    for name in set(n for n in names if isinstance(n,str) and len(n)>=3):
        if names.count(name)!=1:continue
        match=re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',own,re.I)
        if match:matches.append(match.group())
    if len(matches)!=1 or value.comparison or re.search(r'\bcompar\w*\b',text,re.I):return value,[]
    name=matches[0];data=value.model_dump(mode='json');notes=[]
    linked=[]
    for i,row in enumerate(data['requests']):
        if row['reference_id'] or row['polarity']!='request' or row['topic'] not in SUBJECT_TOPICS:continue
        if REPORTED.search(row['evidence']) or row['evidence'] not in own:continue
        # Pronoun material requests may share the only explicit current subject,
        # but unrelated questions cannot inherit a historical or guessed subject.
        if name.casefold() not in row['evidence'].casefold() and not (
            row['topic']=='materials' and re.search(r'\b(?:its|that property|this property)\b',row['evidence'],re.I)
            and re.search(r'\b(?:I prefer|I choose|show me|tell me about)\b',text,re.I)):continue
        linked.append(i)
    if not linked:return value,[]
    existing=next((r['id'] for r in data['references'] if r['kind']=='property' and r['expression'].casefold()==name.casefold() and r['id']),None)
    if existing is None:
        existing='source_property';ids={r['id'] for r in data['references']}
        while existing in ids:existing+='x'
        data['references'].append(dict(id=existing,kind='property',expression=name,evidence=name))
    for i in linked:data['requests'][i]['reference_id']=existing
    notes.append({'field':'references','action':'bind_exact_current_scoped_property','evidence':name,'request_ids':[data['requests'][i]['id'] for i in linked]})
    return Understanding.model_validate(data).check_evidence(text),notes


def completeness_issues(value,text):
    issues=[]
    def add(field,code,message):issues.append({'location':[field],'type':code,'message':message})
    for clause in re.split(r'[.!?;\n]',text):
        if PURPOSE.search(clause) and not REPORTED.search(clause):
            if not any(p.key in {'buyer_type','motivation'} and p.status=='declared' and (p.value in BUYER_SEGMENTS or value.requires_clarification) and PURPOSE.search(p.evidence) and (p.evidence.rstrip('.!?; \n') in clause or clause.strip() in p.evidence) for p in value.preferences):
                add('preferences','own_purchase_purpose_missing','Capture the explicit own buying motivation with its exact current quote and a canonical supported buyer_type/motivation value. If its meaning is genuinely ambiguous, preserve the quote and ask clarification instead of inventing a segment. Do not infer a segment from demographics.')
    if returns_question(text):
        for i,row in enumerate(value.requests):
            if row.polarity=='request' and row.topic.value=='financing' and RETURNS.search(row.evidence) and not re.search(r'\b(?:financing|mortgage|loan|down payment)\b',row.evidence,re.I):
                add('requests','investment_return_as_financing','Rental yield/occupancy is an investment-information question, not financing. Preserve it as other; do not invent figures or approval.')
    if re.search(r'\bprice and availability\b',text,re.I) and any(r.topic.value=='pricing' and r.polarity=='request' for r in value.requests) and not value.permits('inventory'):
        add('requests','availability_question_missing','The current question explicitly asks BOTH price AND availability. Preserve independent pricing and inventory requests, bound to the named property.')
    if re.search(r'\bcompare\b',text,re.I) and not value.comparison and any(r.polarity=='request' and 'compare' in r.evidence.lower() for r in value.requests):
        add('comparison','comparison_missing','Preserve the explicit comparison: define local property references for the exact names and comparison.reference_ids. A comparison does not select either property.')
    return issues
