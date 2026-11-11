"""Structured synthesis: compact, grammatical facts with backend-owned values."""
from dataclasses import replace
import re
from .dialogue_tasks import restricted
from .understanding_contract import Task
from .dialogue_composer import compose
from .response_policy import render_channel_text,split_channel_text


def naturalize(outcome,draft,*,channel):
    tasks={t.id:t for t in outcome.state.tasks}
    rows={};units={};topics=set();handled=set();focus={};general=set();features_wanted={}
    requests={r.id:r for r in outcome.state.last_understanding.requests}
    for result in outcome.results:
        task=tasks.get(result.operation_id)
        if not task or restricted(outcome.state,task) or result.status not in {'success','partial'}:continue
        if 'property_types' not in result.data:continue
        handled.add(task.id);topics.add(task.topic.value)
        for row in [*result.data['property_types'],*result.data.get('units',[])]:
            rid=row['id']
            (units if row.get('unit_code') else rows).setdefault(rid,row)
            focused=[requests[i] for i in task.request_ids if i in requests and requests[i].detail_fields]
            if not focused:general.add(rid)
            for request in focused:
                focus.setdefault(rid,set()).update(request.detail_fields)
                if request.feature:features_wanted[rid]=request.feature

    if not handled:return draft
    rest=replace(outcome,state=outcome.state.model_copy(update={'tasks':[t for t in outcome.state.tasks if t.id not in handled]}))
    other=compose(rest,channel=channel)
    blocks=[]
    def quantity(value,word):return f'{value:g} '+word+('' if value==1 else 's')
    for index,row in enumerate(rows.values(),1):
        facts=[]
        wanted=focus.get(row['id'],set()) if row['id'] not in general else set()
        def allowed(topic):return not restricted(outcome.state,Task(id='narrative',topic=topic,status='pending',property_id=row['id']))
        for key,label in [('bedrooms','bedroom'),('bathrooms','bathroom')]:
            if wanted and key not in wanted:continue
            value=row.get(key)
            if isinstance(value,(int,float)):facts.append(quantity(value,label))
            elif key in wanted:facts.append(label+' count is not confirmed')
        low,high=row.get('area_min'),row.get('area_max')
        if low is not None and (not wanted or 'area' in wanted):
            facts.append(f'{low:g}'+(f'–{high:g}' if high is not None and low!=high else '')+' '+str(row.get('area_unit') or '(area unit unconfirmed)'))
        line=f"{index}. {row['property_type']}"
        if facts:line+=' — '+', '.join(facts)
        if not wanted and allowed('pricing') and row.get('starting_price') is not None and row.get('currency'):line+=f". Published prices start at {row['starting_price']:,.2f} {row['currency']}"
        elif not wanted and allowed('pricing') and 'pricing' in topics:line+='. The price is not confirmed'
        if 'inventory' in topics and allowed('inventory'):
            available=row.get('available_units')
            line+='. Availability is not confirmed' if available is None else f'. Last confirmed quantity: {available}'
        line+='.'
        if 'property_details' in topics or len(rows)==1:
            description=row.get('description')
            # Full reviewed statements only: never cut away a price/feature qualifier.
            if (not wanted or 'description' in wanted) and isinstance(description,str) and len(description)<=1000 and '://' not in description and '?' not in description:line+=' '+description
            features=[v for v in row.get('features') or [] if isinstance(v,str) and len(v)<=300 and '://' not in v and '?' not in v]
            if wanted and not set(wanted)&{'features','kitchen'}:features=[]
            if 'kitchen' in wanted:
                features=[v for v in features if 'kitchen' in v.casefold()]
                if isinstance(description,str):features.extend(v.strip() for v in re.split(r'[.!?]\s+',description) if 'kitchen' in v.casefold() and len(v)<=300 and '://' not in v and '?' not in v)
            if row['id'] in features_wanted:
                tokens=re.findall(r'[a-z0-9]+',features_wanted[row['id']].casefold())
                features=[v for v in features if tokens and all(re.search(r'\b'+re.escape(token)+r'\b',v,re.I) for token in tokens)]
            if features:line+=' Features: '+'; '.join(dict.fromkeys(features[:3]))+'.'
            elif set(wanted)&{'features','kitchen'}:line+=' Those feature details are not confirmed.'
            if 'description' in wanted and not description:line+=' A detailed description is not confirmed.'
            if 'area' in wanted and low is None:line+=' Area details are not confirmed.'
        blocks.append(line)
    for row in units.values():
        facts=[]
        wanted=focus.get(row['id'],set()) if row['id'] not in general else set()
        for key,label in [('bedrooms','bedroom'),('bathrooms','bathroom')]:
            if wanted and key not in wanted:continue
            if isinstance(row.get(key),(int,float)):facts.append(quantity(row[key],label))
            elif key in wanted:facts.append(label+' count is not confirmed')
        if (not wanted or 'area' in wanted) and row.get('area') is not None:facts.append(f"area: {row['area']:g} (unit of measure unconfirmed)")
        text='Unit '+row['unit_code']+(' — '+', '.join(facts) if facts else '')+'.'
        if not wanted and row.get('price') is not None and row.get('currency'):text+=f" The recorded price is {row['price']:,.2f} {row['currency']}."
        elif not wanted and 'pricing' in topics:text+=' The price for this unit is not confirmed.'
        if set(wanted)&{'kitchen','features','description'}:text+=' Those details are not confirmed for this individual unit.'
        if 'area' in wanted and row.get('area') is None:text+=' Area details are not confirmed.'
        if 'inventory' in topics and row.get('status'):text+=' Last recorded status: '+row['status']+'.'
        blocks.append(text)
    if rows:blocks.insert(0,'Here are the property options I can confirm:')
    if other.text!='I need clarification or verified information to answer this request.':blocks.append(other.text)
    text=render_channel_text('\n\n'.join(dict.fromkeys(blocks)),channel)
    return replace(draft,text=text,parts=tuple(split_channel_text(text,channel)))


def empathy_text(u,state,commercial):
    if not u.empathy:return ''
    from .financial_declarations import neutral_courtesy
    if neutral_courtesy(u.empathy.evidence):return ''
    opening={'feeling_unwell':"I'm sorry you're not feeling well. We can take this at your pace.",
             'personal_setback':"I'm sorry you're having a difficult time. There's no rush.",
             'frustrated':"I understand this can feel frustrating. Let's keep things simple."}[u.empathy.kind]
    if any(r.topic.value not in {'other'} and r.polarity=='request' for r in u.requests):return opening
    names={p['id']:p['property_type'] for p in commercial['property_types']}
    name=names.get(state.selected_property_type_id)
    topic=next((t for turn in reversed(state.memory.recent_turns) for t in reversed(turn.get('requested_topics') or []) if t in {'materials','pricing','property_details','catalog','inventory','financing','delivery','amenities','location'}),None)
    label={'materials':'the property materials','pricing':'the pricing details','financing':'payment options','delivery':'delivery timing','location':'the location','amenities':'the features','catalog':'the available options','inventory':'availability'}.get(topic,'the property details')
    return opening+(' When you feel ready, we can pick up with '+label+(' for '+name if name else '')+'.')
