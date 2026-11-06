"""Group 7: grounded diagnostic drafts. No links minted or actions performed."""
from dataclasses import dataclass
from .understanding_contract import ToolResult
from .dialogue_tasks import restricted
from .response_policy import render_channel_text, split_channel_text


@dataclass(frozen=True)
class Draft:
    text: str
    parts: tuple
    asset_ids: tuple
    answered_task_ids: tuple
    pending_task_ids: tuple
    violations: tuple


def compose(outcome, *, channel='sms', style='concise'):
    if style not in {'concise','detailed'}:
        raise ValueError('Unknown composition style.')
    state = outcome.state
    results = {r.operation_id:r for r in outcome.results}
    blocks, materials, assets, answered, pending, violations = [], [], [], [], [], []
    for task in state.tasks:
        result = results.get(task.id)
        if task.status == 'cancelled':
            continue
        if restricted(state,task):
            pending.append(task.id); continue
        if not result or result.status not in {'success','partial'}:
            if task.status != 'completed':
                pending.append(task.id)
                if result and task.topic.value not in {'appointment','human','opt_out'}:
                    blocks.append(f"{task.topic.value.capitalize()}: verified information is not available in this query.")
            continue
        result = ToolResult.model_validate(result.model_dump())
        data = result.data
        if task.topic.value == 'materials':
            for item in data.get('materials',[]):
                if item['asset_id'] not in assets:
                    assets.append(item['asset_id'])
                    tags = ', '.join(item.get('content_tags') or [])
                    qualification = 'Photo coverage is not confirmed. ' if not data.get('coverage_confirmed') else ''
                    materials.append(f"Available material: {item['name']}. Contents: {tags}. {qualification}Not sent yet.")
            pending.append(task.id)  # Discovery is not fulfillment.
        elif 'property_types' in data:
            rows = data['property_types']
            summaries = []
            for index, item in enumerate(rows,1):
                facts = []
                for key,label in [('bedrooms','bedrooms'),('bathrooms','bathrooms')]:
                    if key == 'bathrooms' and style == 'concise' and task.topic.value != 'property_details': continue
                    if item.get(key) is not None: facts.append(f"{item[key]} {label}")
                if item.get('area_min') is not None:
                    area = str(item['area_min'])
                    if item.get('area_max') != item['area_min'] and item.get('area_max') is not None: area += '–'+str(item['area_max'])
                    facts.append(area+' '+str(item.get('area_unit') or ''))
                if item.get('starting_price') is not None and item.get('currency'):
                    facts.append(f"from {item['starting_price']:,.2f} {item['currency']}")
                if task.topic.value == 'inventory':
                    facts.append('quantity unconfirmed' if item.get('available_units') is None else f"{item['available_units']} confirmed units")
                summaries.append(f"{index}. {item['property_type']}\n"+' · '.join(facts))
                if task.topic.value == 'property_details':
                    if isinstance(item.get('description'),str): summaries[-1] += '\n'+item['description']
                    features = item.get('features') or []
                    if features: summaries[-1] += '\n'+'; '.join(v for v in features if isinstance(v,str))
            if summaries:
                blocks.append('Confirmed catalog:\n\n'+'\n\n'.join(summaries)+'\n\nCatalog coverage may be partial.')
                if task.topic.value == 'pricing' and not all(p.get('starting_price') is not None and p.get('currency') for p in rows):
                    blocks.append('Some requested prices have not been confirmed.')
                    pending.append(task.id)
                else:
                    answered.append(task.id)
        elif data.get('value') is not None:
            value = data['value']
            if isinstance(value,list):
                if any(not isinstance(v,(str,int,float)) for v in value):
                    violations.append('unsupported_fact_shape'); pending.append(task.id); continue
                value = '; '.join(str(v) for v in value)
            if not isinstance(value,(str,int,float)):
                violations.append('unsupported_fact_shape'); pending.append(task.id); continue
            blocks.append(f"{task.topic.value.capitalize()}: {value}.")
            answered.append(task.id)
    clarification = state.last_understanding
    if clarification and clarification.requires_clarification:
        blocks.append(clarification.clarification_question)
    if not blocks and not materials:
        blocks.append('I need clarification or verified information to answer this request.')
    if any(t.topic.value in {'property_details','materials','pricing','inventory'} and t.status == 'awaiting_user' for t in state.tasks):
        blocks.append('Which property option would you like to explore?')
    # Repair is deterministic composition from facts, not another tool execution.
    text = render_channel_text('\n\n'.join([*blocks,*materials]),channel)
    return Draft(text,tuple(split_channel_text(text,channel)),tuple(assets),tuple(answered),tuple(pending),tuple(violations))
