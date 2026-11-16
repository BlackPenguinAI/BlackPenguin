"""Commercial continuations after successful material delivery; no action authority."""
VERSION='sales-material-continuity/1.0'

def choices(outcome,commercial,metadata,previous_meta,holds,booked):
    u=outcome.state.last_understanding
    if not metadata.get('material_bindings'):return None
    topics={r.topic.value for r in u.requests if r.polarity=='request'}
    # Independent questions and operational summaries retain their own closing.
    if topics!={'materials'}:return None
    state=outcome.state
    owners=[p for p in commercial.get('property_types',[]) if p.get('id')==state.selected_property_type_id]
    silent={'id':'material_review','text':'','metadata':{'material_continuity':{'version':VERSION,'decision':'allow_review','integral_dialogue_quality':'NOT_EVALUATED'}}}
    if len(owners)!=1 or state.selected_unit_id or previous_meta.get('material_continuity'):return [silent]
    name=owners[0].get('property_type')
    if not name:return [silent]
    blocked=booked or 'appointment' in holds or bool(state.booking_search or state.booking_proposal)
    blocked|=any(c.topic.value=='appointment' for c in state.constraints)
    blocked|=any(c.topic.value=='appointment' and (c.binding_status=='unresolved' or not c.property_id or c.property_id==state.selected_property_type_id) for c in state.property_constraints)
    if u.courtesy or u.empathy or blocked or previous_meta.get('visit_invitation'):return [silent]
    # A single relevant question; facts about file contents are never inferred.
    bedrooms=next((p.value for p in reversed(state.preferences) if p.key=='bedrooms' and str(p.value).isdigit()),None)
    text=(f'You mentioned that {bedrooms} bedrooms would work for you. What matters most to you about {name}?' if bedrooms else f'What would you like to explore further about {name}?')
    result=[{'id':'material_interest','text':text,'metadata':{'material_continuity':{'version':VERSION,'decision':'explore_current_property','property_id':state.selected_property_type_id,'integral_dialogue_quality':'NOT_EVALUATED'}}},silent]
    result.insert(1,{'id':'material_visit','text':f'Would you like to see {name} in person?','metadata':{'visit_invitation':True,'material_continuity':{'version':VERSION,'decision':'offer_visit','property_id':state.selected_property_type_id,'integral_dialogue_quality':'NOT_EVALUATED'}}})
    return result
