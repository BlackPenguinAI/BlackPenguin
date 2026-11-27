"""Supplemental HEI-06 synthetic evidence, never imported by production.

Only known boolean/count/enum fields and static source positions are exported.
Do not expose buyer text, model output, IDs, tool arguments, URLs or exceptions.
"""
from __future__ import annotations
import dis
import json
import re
from pathlib import Path

PROPERTY='hei06_lifecycle_v1'
MAX_EVENTS=100
STAGES={'before_sdk','after_sdk','prepared','persisted','outbound','sdk_tool','domain_tool','failure'}
FLAGS={'primary_budget_350k','primary_beds_exact3','primary_source_current','primary_has_source',
       'search_current','search_budget_100k','search_budget_400k','search_beds6','search_beds4',
       'menu_display_name_bound','menu_has_receipt','offer_has_receipt','offer_matches_menu',
       'confirmation_has_receipt','prepared_visit','primary_captured','no_match_text',
       'van_buren','oakwood','cedar_grove','question','not_booked','confirm_text'}
COUNTS={'primary_revision','search_match_count','menu_options','numbered_lines'}
ENUMS={'menu_type':{'none','property','visit_day','visit_time','media'},
       'search_scope':{'none','temporary','permanent'},
       'confirmation_status':{'none','recap_required','awaiting_confirmation','execution_requested','committed','cancelled','rescheduled'},
       'choice_type':{'none','property','visit_day','visit_time','media'},
       'tool':{'search_properties','evaluate_properties_for_lead','get_project_overview','get_unit_details','compare_properties','list_unit_assets','get_unit_media','update_search_preferences','update_lead_profile','get_available_visit_slots','select_visit_time','book_onsite_visit','cancel_onsite_visit','reschedule_onsite_visit','track_property_interest'},
       'status':{'executed','rejected'},
       'error_code':{'VISIT_SELECTION_ALREADY_RESOLVED','DELIVERED_OFFER_REQUIRED','STALE_PROPOSAL','SLOT_NOT_OFFERED','SELECTION_EVIDENCE_REQUIRED','VISIT_CHOICE_AMBIGUOUS','BOOKING_CONFIRMATION_REQUIRED','BOOKING_DETAILS_MISMATCH','EXPLICIT_BOOKING_CONSENT_REQUIRED','SEPARATE_TURN_REQUIRED','PREFERENCE_EVIDENCE_REQUIRED','TEMPORARY_SEARCH_ONLY','SOURCE_MESSAGE_REQUIRED','GLOBAL_TOOL_DISABLED','P01_EFFECTS_DISABLED','COMMERCIAL_POLICY_HOLD','PERMISSIONERROR','PROPERTY_REFERENCE_CONFLICT','PROPERTY_REQUIRED','INVALID_SEARCH','PERMANENT_SCOPE_REQUIRES_EVIDENCE','TOOL_ARGUMENT_INVALID','VISIT_LOCATION_REQUIRED'},
       'failure_type':{'AssertionError','ProductionToolError','ValueError','KeyError','TypeError','PermissionError','RuntimeError','HTTPException'},
       'failure_function':{'exercise','accepted_no_match','comparison_facts','fact','no_business_effect'},
       'failure_reason':{'preference_capture','preference_changed','monetary_guard','language_guard','visit_selection_reconciliation','unknown'}}
FAILURE_REASONS={'Explicit preference capture requires reconciliation.':'preference_capture',
                 'Explicit preference draft changed after inference.':'preference_changed',
                 'Reply requires monetary reconciliation before dispatch.':'monetary_guard',
                 'Reply requires language reconciliation before dispatch.':'language_guard',
                 'Verified visit selection requires reconciliation.':'visit_selection_reconciliation'}


def _enum(value, allowed):
    return value if isinstance(value,str) and value in allowed else 'unknown'


def clean(event):
    if not isinstance(event,dict) or event.get('stage') not in STAGES:
        return None
    out={'stage':event['stage']}
    for k in FLAGS:
        if type(event.get(k)) is bool:out[k]=event[k]
    for k in COUNTS:
        if type(event.get(k)) is int and 0<=event[k]<=100000:out[k]=event[k]
    for k,allowed in ENUMS.items():
        if k in event:out[k]=None if k=='error_code' and event[k] is None else _enum(event[k],allowed)
    for k in ('failure_line','failure_column'):
        if type(event.get(k)) is int and 0<=event[k]<=2000:out[k]=event[k]
    return out


def state_shape(state,inbound_id=None,*,menus=None):
    if not isinstance(state,dict):return {}
    prefs=state.get('search_preferences') or {}; budget=prefs.get('budget') or {}; beds=prefs.get('bedrooms') or {}
    search=state.get('active_search') or {}; c=search.get('criteria') or {}
    menu=state.get('last_presented_choice_set') or {}
    if menus is not None:menu=menus[-1] if menus else {}
    offer=state.get('last_slot_search') or {}; req=state.get('confirmation_request') or {}
    def count_matches(value):
        return c.get('bedrooms')==value or c.get('bedrooms_any')==[value] or c.get('bedrooms_min')==c.get('bedrooms_max')==value
    return {'primary_budget_350k':budget.get('maximum_usd')==350000,
            'primary_beds_exact3':beds.get('mode')=='exact' and beds.get('preferred')==3,
            'primary_revision':prefs.get('revision',0),'primary_has_source':bool(prefs.get('last_source_message_id')),
            'primary_source_current':bool(inbound_id and prefs.get('last_source_message_id')==inbound_id),
            'search_current':bool(inbound_id and search.get('source_inbound_message_id')==inbound_id),
            'search_scope':search.get('scope') or 'none','search_match_count':search.get('match_count'),
            'search_budget_100k':c.get('max_price_usd')==100000,'search_budget_400k':c.get('max_price_usd')==400000,
            'search_beds6':count_matches(6),'search_beds4':count_matches(4),
            'menu_type':menu.get('type') or 'none','menu_options':len(menu.get('options') or []),
            'menu_display_name_bound':bool(menu.get('display_name')),'menu_has_receipt':bool(menu.get('source_reply_message_id')),
            'offer_has_receipt':bool(offer.get('source_reply_message_id')),
            'offer_matches_menu':bool(menu.get('unit_id') and menu.get('unit_id')==offer.get('unit_id') and menu.get('proposal_id')==offer.get('proposal_id')),
            'confirmation_status':req.get('status') or 'none','confirmation_has_receipt':bool(req.get('recap_message_id'))}


def reply_shape(text):
    if not isinstance(text,str):return {}
    plain=re.sub(r'[*_`]','',text[:20000].casefold())
    return {'van_buren':'van buren' in plain,'oakwood':'oakwood' in plain,'cedar_grove':'cedar grove' in plain,
            'numbered_lines':min(20,len(re.findall(r'^\s*\d+[.)]\s+',plain,re.M))),
            'question':'?' in plain,'not_booked':'not booked' in plain,'confirm_text':'confirm' in plain,
            'no_match_text':bool(re.search(r'\b(?:no (?:verified |available |matching )?(?:matches|houses|homes|properties|options|results)|could not find|cannot find|none match)\b',plain))}


class LifecycleEvidence:
    def __init__(self):self.events=[];self.truncated=False
    def add(self,stage,**fields):
        item=clean({'stage':stage,**fields})
        if item is None:return
        if len(self.events)>=MAX_EVENTS:self.truncated=True;return
        self.events.append(item)
    def tools(self,stage,observations):
        for item in (observations or [])[:50]:
            if isinstance(item,dict):self.add(stage,tool=item.get('tool'),status=item.get('status'),error_code=item.get('error_code'))
    def failure(self,exc):
        fields={'failure_type':type(exc).__name__,'failure_reason':FAILURE_REASONS.get(str(exc),'unknown')}
        # Location only in the static acceptance file; no source text or locals.
        tb=exc.__traceback__
        while tb:
            code=tb.tb_frame.f_code
            if Path(code.co_filename).name=='staging_scenarios.py' and code.co_name in ENUMS['failure_function']:
                fields.update(failure_function=code.co_name,failure_line=tb.tb_lineno)
                try:
                    pos=next((x.positions for x in dis.get_instructions(code,show_caches=True) if x.offset==tb.tb_lasti),None)
                    if pos is not None and pos.col_offset is not None:fields['failure_column']=pos.col_offset
                except (TypeError,ValueError):pass
            tb=tb.tb_next
        self.add('failure',**fields)
    def serialized(self):return json.dumps({'events':self.events,'truncated':self.truncated},separators=(',',':'))


def parse_lifecycle(case):
    props=[p.get('value','') for p in case.findall('./properties/property') if p.get('name')==PROPERTY]
    if len(props)!=1 or len(props[0])>65536:return {'status':'MISSING_OR_INVALID','events':[]}
    try:
        raw=json.loads(props[0]);events=raw.get('events') if isinstance(raw,dict) else None
        if not isinstance(events,list) or not events or len(events)>MAX_EVENTS:raise ValueError
        safe=[clean(e) for e in events]
        if any(x is None for x in safe):raise ValueError
        return {'status':'TRUNCATED' if raw.get('truncated') is True else 'RECORDED','events':safe}
    except (ValueError,TypeError):return {'status':'MISSING_OR_INVALID','events':[]}
