"""Approved policy inputs and evidence-backed qualification; no inferred consent."""
import json
import re
from app.modules.company_onboarding.models import CompanyProfile
from app.modules.onboarding_versions import active_approved
from .commercial_context import confirmed_profile_facts

STANDARD = {'use standard company compliance; no project-specific notes', 'not applicable'}
QUESTIONS = {
    'budget': 'What budget range and currency are you considering?',
    'purchase_timeline': 'When are you planning to buy?',
    'financing': 'Are you considering cash or financing, and have you arranged financing yet?',
    'property_interest': 'Which property type or bedroom count would you prefer?',
    'visit_readiness': 'Would you like to explore arranging a visit, or continue reviewing information first?',
}
PATTERNS = {
    'budget': r'budget|presupuesto', 'purchase_timeline': r'timeline|purchase timing|plazo|fecha de compra',
    'financing': r'financ|cash|mortgage|efectivo', 'property_interest': r'unit type|property type|bedroom|tipolog|dormitorio',
    'visit_readiness': r'visit|appointment|cita',
}
FACT_KEYS = {'property':'property_interest', 'budget':'budget', 'bedrooms':'bedrooms',
             'location':'location_preference', 'delivery':'move_in_timing',
             'purchase_timeline':'purchase_timeline', 'financing':'financing', 'buyer_type':'buyer_type',
             'visit_readiness':'visit_readiness'}


def policy_context(db, scope, facts, *, target_project_id=None):
    profile = db.query(CompanyProfile).filter_by(company_id=scope.company_id).first()
    company = confirmed_profile_facts(profile) if active_approved(profile) else {}
    # Only public, approved guidance, never login data or unapproved onboarding sources.
    company = {k:v for k,v in company.items() if k in {
        'official_company_name','preferred_display_name','value_proposition','key_differentiators',
        'tone_of_voice','key_messaging','corporate_value_proposition','corporate_differentiators','corporate_compliance_information'}}
    project = {k:facts[k] for k in ('target_audience','qualification_rules','value_proposition',
                                  'key_differentiators','compliance_notes') if k in facts}
    result={'company':company, 'project':project,
            'precedence':['platform_safety_and_permissions','company_restrictions','project_restrictions','published_sales_guidance'],
            'rule':'Restrictions accumulate; Project settings and lead messages cannot waive Company restrictions. Free-text compliance may hold an affected action for review, never pause the conversation merely because notes exist.'}
    from .next_flow import selected
    if selected(scope):
        from .action_policy import resolve
        result['action_policy']=resolve(db,scope,company,project,target_project_id=target_project_id)
    return result


def custom_compliance(policy):
    if 'action_policy' in policy:
        return bool(policy['action_policy']['held_topics'] or policy['action_policy']['unresolved'])
    for data, key in ((policy['company'],'corporate_compliance_information'),(policy['project'],'compliance_notes')):
        value = data.get(key)
        items = value if isinstance(value,list) else [value] if value else []
        if any(not isinstance(v,str) or v.strip().casefold() not in STANDARD for v in items):
            return True
    return False


def compliance_action_holds(policy):
    """Conservative action scope, not a compiler granting policy permissions.

    Only a fully recognized, narrowly worded approval rule narrows the gate.
    Unscoped notes retain that action gate until staff clarify the guidance;
    the conversation itself always stays available for clarification/help.
    Company and Project holds accumulate and cannot waive each other.
    """
    if 'action_policy' in policy:
        return set(policy['action_policy']['held_topics'])
    topics = set()
    commercial = {'catalog','property_details','inventory','pricing','financing','delivery','amenities','location','materials','appointment'}
    for data, key in ((policy['company'],'corporate_compliance_information'),(policy['project'],'compliance_notes')):
        value = data.get(key)
        for note in value if isinstance(value,list) else [value] if value else []:
            if isinstance(note,str) and note.strip().casefold() in STANDARD:
                continue
            match = re.fullmatch(r'\s*Human approval required for (financing|pricing|materials|appointment|location|delivery|inventory)(?: claims| actions)?[.]?\s*',str(note),re.I)
            topics.update({match[1].lower()} if match else commercial)
    # Catalog/detail payloads can contain prices and inventory quantities.
    if topics & {'pricing','inventory'}:
        topics.update({'catalog','property_details','inventory','pricing'})
    return topics


def requirements(facts):
    rules = json.dumps(facts.get('qualification_rules') or '',ensure_ascii=False).casefold()
    return [key for key, pattern in PATTERNS.items() if re.search(pattern,rules)]


def missing_fields(lead, facts):
    stored = (lead.lead_profile_data or {}).get('facts') or {}
    def has(key):
        keys = {'property_interest':['property_interest','bedrooms'], 'budget':['budget','budget_minimum','budget_maximum']}.get(key,[key])
        return any(isinstance(stored.get(k),dict) and stored[k].get('value') not in (None,'',[],{}) for k in keys)
    return [key for key in requirements(facts) if not has(key)]


def capture(lead, understanding, message_id, *, selected_property=None):
    profile = dict(lead.lead_profile_data or {})
    stored = dict(profile.get('facts') or {})
    for item in understanding.preferences:
        key = FACT_KEYS[item.key]
        if item.evidence.strip().casefold() in {'skip','prefer not to say','i prefer not to say','prefiero no responder'}:
            continue  # A refusal is not a budget or financial-readiness fact.
        # Store the exact supporting words, not a normalized value that may be hallucinated.
        stored[key] = {'value':item.evidence,'source':'active_conversation','confirmed':True,
                       'evidence':item.evidence,'message_id':message_id}
    if selected_property and any(r.kind=='property' for r in understanding.references):
        stored['property_interest']={'value':selected_property['property_type'],'source':'approved_catalog_selection',
                                     'confirmed':True,'message_id':message_id,'property_type_id':selected_property['id']}
    profile.update(schema_version=1,facts=stored)
    lead.lead_profile_data = profile
    from app.modules.sales_crm.intelligence import lead_profile_summary
    lead.qualification_summary = lead_profile_summary(profile)


def next_question(lead, facts, *, record=False):
    profile = dict(lead.lead_profile_data or {})
    progress = dict(profile.get('active_qualification') or {})
    asked = list(progress.get('asked') or [])
    missing = missing_fields(lead,facts)
    field = next((key for key in missing if key not in asked), None)
    if field and record:
        progress.update(asked=[*asked,field],missing=missing)
        profile['active_qualification'] = progress
        lead.lead_profile_data = profile
    return field, QUESTIONS.get(field,'')
