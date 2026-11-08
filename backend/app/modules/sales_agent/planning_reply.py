"""Useful bounded continuation from planning evidence, never action claims."""


def continuation(outcome,holds):
    plan=getattr(outcome,'plan',None) or {}
    questions=plan.get('questions') or []
    if questions:
        from .turn_configuration import digest
        context={'reference_question':True,
            'clarification_tasks':[row['task_id'] for row in plan['request_coverage'] if row.get('task_id') and any(q['request_id']==row['request_id'] for q in questions)],
            'clarification_restrictions':[digest({'topic':c.topic,'subject':c.subject,'evidence':c.evidence}) for c in outcome.state.property_constraints if c.binding_status=='unresolved']}
        options=[]
        for question in questions:
            for row in question['options']:
                if row not in options:options.append(row)
        if options and not {'catalog','property_details'}&holds:
            # One displayed kind keeps subsequent ordinals unambiguous.
            kind=options[0]['kind'];options=[o for o in options if o['kind']==kind][:20]
            text='Which '+('unit' if kind=='unit' else 'property option')+' do you mean?\n\n'+'\n'.join(f"{i}. {o['label']}" for i,o in enumerate(options,1))
            key,ids=('unit_catalog_offer','unit_ids') if kind=='unit' else ('property_catalog_offer','property_type_ids')
            return text,{key:{ids:[o['id'] for o in options],'labels':[o['label'] for o in options]},**context}
        return 'Please clarify whether you mean a property, unit, material or appointment time.',context
    if outcome.stop_reason in {'step_limit','time_limit','round_limit','read_cost_limit','capacity_limit'}:
        topics=plan.get('pending_topics') or []
        text='I still have requests to review'+(': '+', '.join(t.replace('_',' ') for t in topics[:4]) if topics else '')+'. Which would you like me to handle next?'
        return text,{}
    if 'appointment' in plan.get('pending_topics',[]) and not outcome.state.last_understanding.permits('appointment'):
        return "We can return to arranging your visit when you're ready.",{}
    return '',{}
