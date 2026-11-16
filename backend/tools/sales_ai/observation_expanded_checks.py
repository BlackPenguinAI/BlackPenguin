"""Explicit outcome checks for the nine added scripts; not a dialogue-quality judge."""
from .evaluation_checks import check

def turn_checks(row,key):
    meta=row.get('metadata') or {};reply=row.get('reply','');action=row['action'];checks=[]
    bindings=meta.get('material_bindings') or []
    def add(name,value):checks.append(check(name,bool(value)))
    if bindings:
        add('material_has_contextual_continuation','?' in reply or action=='post_material' and meta.get('meeting_id'))
        add('at_most_one_material_followup_question',reply.count('?')<=1)
    if action in {'mixed','mixed_unknown','post_material'}:
        add('requested_pdf_delivered',any(b['binding'].get('mime_type')=='application/pdf' for b in bindings))
        add('independent_financing_addressed',any(w in reply.lower() for w in ('financing','mortgage','payment','rate')))
        if action=='mixed':
            offer=meta.get('material_offer') or {}
            add('pending_gallery_offered',any(i['binding'].get('type')=='gallery_image' for i in offer.get('items',[])))
    if action=='mixed_unknown':
        add('unknown_financing_disclosed',any(w in reply.lower() for w in ('not available','not have','not confirmed',"don't have",'not published','not provided','unavailable','do not have published')))
    if action in {'accept_material','accept_gallery'}:
        add('accepted_material_delivered',bool(bindings))
    if action=='post_material':
        add('no_new_booking_offer_after_confirmed_visit',not meta.get('appointment_offer') and not meta.get('booking_confirmation'))
    if action=='farewell':
        add('farewell_without_generic_menu',not any(w in reply.lower() for w in ('clarify whether','property details, materials','what would you like')))
    if action=='layout':
        add('layout_answer_not_generic_clarification',bool(reply) and 'clarify whether' not in reply.lower() and any(w in reply.lower() for w in ('layout','room','floor','bedroom')))
    if key=='ext_pdf_only' and bindings:
        add('visit_suggested_without_gallery',any(w in reply.lower() for w in ('visit','in person','viewing')))
    return checks

def evaluate(db,manifest,result,spec):
    from app.modules.sales_crm.models import Lead,Meeting,MeetingStatus
    from app.modules.sales_agent.dialogue_store import Scope,load
    sent=set()
    for row in result['turns']:
        row['checks'].extend(turn_checks(row,result['case']))
        meta=row.get('metadata') or {}
        sent.update(b['binding']['asset_id'] for b in meta.get('material_bindings',[]))
        offered=set((meta.get('material_offer') or {}).get('asset_ids',[]))
        row['checks'].append(check('no_offer_of_already_delivered_material',not offered&sent))
        if result['case']=='ext_compare_layout' and row['action'] in {'choose_second','layout'}:
            target=manifest['projects'][spec['project']]['properties'][spec['property']]['id']
            row['checks'].append(check('second_property_remains_selected',meta.get('selected_property_type_id')==target))
    lead=db.get(Lead,result['lead_id'])
    if result['case']=='ext_bedroom_acceptance':
        _,state=load(db,Scope(manifest['company_id'],lead.project_id,result['conversation_id'],lead.id))
        result['checks'].append(check('accepted_bedroom_count_saved',any(p.key=='bedrooms' and str(p.value)=='4' for p in state.preferences)))
    if result['case']=='ext_booked_questions':
        meetings=db.query(Meeting).filter_by(lead_id=lead.id,status=MeetingStatus.CONFIRMED).all()
        result['checks'].extend([check('existing_booking_preserved',len(meetings)==1),check('confirmed_booking_intent_reflected',(lead.intent_score or 0)>=.35)])
        result['checks'].append(check('post_booking_questions_and_farewell_executed',{'post_material','farewell'}<={r['action'] for r in result['turns']}))
    if result['case']=='ext_booked_questions':
        ids=[r.get('meeting_ids') for r in result['turns'] if r['action'] in {'confirm','post_material','farewell'}]
        result['checks'].append(check('same_booking_through_post_booking_turns',len(ids)==3 and all(v==ids[0] for v in ids)))
    result['review_required']=['Naturalness and persuasion','Accuracy of financing details and material descriptions','Segment only when evidenced; follow-up consent preserved']
