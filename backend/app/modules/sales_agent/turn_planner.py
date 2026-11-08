"""Bounded result-driven planning. Interpretation is upstream; writes are downstream."""
from dataclasses import dataclass
import hashlib
import json
from .dialogue_orchestrator import TurnOutcome
from .dialogue_store import load,save,check_scope,DialogueConflict
from .dialogue_models import SalesDialogueEvent
from .understanding_contract import Understanding,DialogueState,Task,PropertyConstraint,ToolResult
from .dialogue_tasks import task_id,restricted,record_result
from .dialogue_tools import ReadTools,ToolCall
from .reference_resolution import Resolver
from .conversation_scope import scoped_messages_query
from .models import SalesMessage
from .turn_configuration import digest

VERSION='sales-turn-planner/1.0'
BOUND_TOPICS={'property_details','materials','pricing','inventory','appointment'}
WRITE_TOPICS={'appointment','human','opt_out'}
COST={'catalog':2,'inventory':2,'materials':2,'appointment':2}
LIVE={'pending','blocked','suspended','awaiting_user'}


@dataclass(frozen=True)
class PlannedOutcome(TurnOutcome):
    plan:dict|None=None


def run(db,scope,*,message_id,understanding,expected_revision,event_key,max_steps,max_seconds,max_rounds,max_read_units,clock):
    conversation=check_scope(db,scope)
    message=scoped_messages_query(db,conversation).filter_by(id=message_id,direction='inbound',role='user').one()
    if (message.metadata_json or {}).get('lead_id',scope.lead_id)!=scope.lead_id:raise PermissionError('Foreign inbound evidence.')
    u=Understanding.model_validate(understanding.model_dump() if isinstance(understanding,Understanding) else understanding).check_evidence(message.content)
    fingerprint=digest({'version':VERSION,'message_id':message_id,'understanding':u.model_dump(mode='json'),
        'expected_revision':expected_revision,'max_steps':max_steps,'max_seconds':max_seconds,'max_rounds':max_rounds,'max_read_units':max_read_units})
    previous=scope.query(db,SalesDialogueEvent).filter_by(event_key=event_key).first()
    if previous:
        metadata=previous.payload_json['metadata']
        if metadata.get('runtime_fingerprint')!=fingerprint:raise DialogueConflict('Planning event key reused with different input or limits.')
        return PlannedOutcome(previous.revision,DialogueState.model_validate(previous.state_after),
            tuple(ToolResult.model_validate(r) for r in metadata['results']),metadata['stop_reason'],metadata['plan'])
    revision,state=load(db,scope)
    if revision!=expected_revision:raise DialogueConflict('Dialogue revision changed.')
    started=clock()
    resolver=Resolver(db,scope,state)
    references={r.id or 'legacy-'+str(i):resolver.resolve(r) for i,r in enumerate(u.references)}
    values=[r['value'] for r in references.values() if r['status']=='resolved' and r['value']['kind'] in {'property','unit'}]
    subjects={(v.get('property_id'),v.get('unit_id')) for v in values}
    selection=references.get(u.selected_reference_id,{}).get('value') if u.selected_reference_id else values[0] if len(subjects)==1 else None
    if selection:
        state.selected_property_type_id=selection.get('property_id')
        state.selected_unit_id=selection.get('unit_id')
    from .turn_context import latest_outbound
    latest=latest_outbound(db,conversation.id,skip_language_holds=True)
    question_meta=(latest.metadata_json or {}) if latest else {}
    resumed=[]
    if selection and question_meta.get('reference_question') and not u.requires_clarification:
        hashes=question_meta.get('clarification_restrictions') or []
        for c in state.property_constraints:
            if c.binding_status=='unresolved' and digest({'topic':c.topic,'subject':c.subject,'evidence':c.evidence}) in hashes:
                c.property_id=selection.get('property_id');c.unit_id=selection.get('unit_id');c.binding_status='resolved'
        if all(r.topic.value in {'other','property_details','catalog'} for r in u.requests if r.polarity=='request'):
            payload=u.model_dump(mode='json')
            for old in state.tasks:
                if old.id not in (question_meta.get('clarification_tasks') or []) or old.topic.value in WRITE_TOPICS or old.status!='awaiting_user':continue
                identifier='clarified_'+old.id[:20]
                ref=next((r for r in u.references if (r.id or '')==u.selected_reference_id),u.references[0] if u.references else None)
                if ref is None:continue
                payload['requests'].append({'id':identifier,'topic':old.topic.value,'subject':old.subject,'polarity':'request','evidence':ref.evidence,'reference_id':ref.id})
                payload['all_of'].append(identifier);resumed.append({'task_id':old.id,'request_id':identifier})
                old.status='cancelled';old.blocked_reason='clarified_by_current_answer'
            u=Understanding.model_validate(payload)
    from .request_safety import apply_vetoes,prohibited,explicit_reversal
    scoped=any(r.reference_id for r in u.requests) or any(c.reference_id for c in u.constraints)
    if not scoped:u=apply_vetoes(u,message.content)
    state.constraints=[c for c in state.constraints if c.scope=='until_explicit_change']
    state.property_constraints=[c for c in state.property_constraints if c.scope=='until_explicit_change']
    for release in u.releases:
        if explicit_reversal(release.evidence) and u.permits(release.topic,release.subject):
            state.constraints=[c for c in state.constraints if not(c.topic==release.topic and c.subject==release.subject)]
            state.property_constraints=[c for c in state.property_constraints if not(c.topic==release.topic and c.subject==release.subject
                and c.binding_status=='resolved' and c.property_id==state.selected_property_type_id and c.unit_id==state.selected_unit_id)]
    def restriction(topic,subject,scope_value,evidence,link):
        if not link:
            from .understanding_contract import Constraint
            item=Constraint(topic=topic,subject=subject,scope=scope_value,evidence=evidence)
            if not any((c.topic,c.subject,c.scope)==(item.topic,item.subject,item.scope) for c in state.constraints):state.constraints.append(item)
        else:
            value=references.get(link,{}).get('value') or {}
            item=PropertyConstraint(topic=topic,subject=subject,scope=scope_value,evidence=evidence,
                property_id=value.get('property_id'),unit_id=value.get('unit_id'),
                binding_status='resolved' if value.get('kind') in {'property','unit'} else 'unresolved')
            if not any((c.topic,c.subject,c.scope,c.property_id,c.unit_id,c.binding_status)==(item.topic,item.subject,item.scope,item.property_id,item.unit_id,item.binding_status) for c in state.property_constraints):state.property_constraints.append(item)
    if scoped and prohibited(message.content,'appointment'):
        restriction('appointment',None,'until_explicit_change',message.content[:2000],None)
    for c in u.constraints:restriction(c.topic,c.subject,c.scope,c.evidence,c.reference_id)
    for r in u.requests:
        if r.polarity=='exclude':restriction(r.topic,r.subject,'turn',r.evidence,r.reference_id)
    for p in u.preferences:state.preferences=[v for v in state.preferences if v.key!=p.key]+[p]
    state.last_understanding=u
    plan={'version':VERSION,'references':references,'request_coverage':[], 'rounds':[], 'questions':[],
          'read_units':0,'tool_calls':0,'additional_model_calls':0,'external_actions':0,
          'limits':{'steps':max_steps,'rounds':max_rounds,'seconds':max_seconds,'read_units':max_read_units},
          'retired_tasks':[],'deferred_requests':[],'write_candidates_require_backend_authorization':[]}
    plan['interest_reference']=next((key for key,value in references.items() if value.get('value')==selection),None) if selection else None
    plan['resumed_requests']=resumed
    for c in state.property_constraints:
        if c.binding_status=='unresolved':plan['questions'].append({'request_id':None,'reason':'restriction_reference_clarification','options':resolver.options()})
    current=[]
    groups={rid:message.id+':'+g.id for g in u.alternatives for rid in g.request_ids}
    for r in u.requests:
        if r.polarity!='request':
            plan['request_coverage'].append({'request_id':r.id,'status':'excluded'});continue
        linked=references.get(r.reference_id) if r.reference_id else None
        relevant=[v for v in references.values() if v.get('value',{}).get('kind') in {'property','unit'} or v['status']=='clarification']
        if linked is None and r.topic.value in BOUND_TOPICS and len(relevant)==1:linked=relevant[0]
        value=(linked or {}).get('value') or {}
        unresolved=bool(linked and linked['status']!='resolved') or not r.reference_id and r.topic.value in BOUND_TOPICS and len(subjects)>1
        task=Task(id=task_id(message.id,r.id),topic=r.topic,subject=r.subject,request_ids=[r.id],source_message_id=message.id,
            status='awaiting_user' if u.requires_clarification or unresolved else 'pending',alternative_group=groups.get(r.id),
            property_id=value.get('property_id',state.selected_property_type_id) if r.topic.value in BOUND_TOPICS else None,
            unit_id=value.get('unit_id',state.selected_unit_id) if r.topic.value in BOUND_TOPICS else None,
            binding_status='unresolved' if unresolved else 'resolved' if value or state.selected_property_type_id or state.selected_unit_id else 'unspecified',
            blocked_reason='reference_clarification' if unresolved else None)
        if (not unresolved and not task.property_id and not task.unit_id and
            task.topic.value in {'property_details','materials'} and len(resolver.types)==1):
            # A single approved option is an unambiguous query target, not
            # evidence of purchase interest or appointment consent.
            task.property_id=next(iter(resolver.types))
            task.binding_status='resolved'
        if scoped and prohibited(r.evidence,'appointment' if r.topic.value=='appointment' else r.subject or r.topic.value):
            task.status='blocked';task.blocked_reason='negative_current_evidence'
        if unresolved:
            plan['questions'].append({'request_id':r.id,'reason':'reference_clarification',
                'options':(linked or {}).get('options') or resolver.options()})
        for old in state.tasks:
            if old.status in LIVE and (old.topic,old.subject,old.property_id,old.unit_id)==(task.topic,task.subject,task.property_id,task.unit_id):
                old.status='cancelled';old.blocked_reason='superseded_by_current_request'
        current.append(task)
    # Retire terminal tasks to the immutable event history, keeping all dependency
    # targets still needed by open tasks. The state is a working set, not the audit.
    needed={dep for t in state.tasks if t.status in LIVE for dep in t.depends_on}
    for _ in range(len(state.tasks)):
        expanded=needed|{dep for t in state.tasks if t.id in needed for dep in t.depends_on}
        if expanded==needed:break
        needed=expanded
    terminal=[t for t in state.tasks if t.status not in LIVE and t.id not in needed]
    keep_count=max(0,min(20,100-len(current)-len(state.tasks)+len(terminal)))
    keep={t.id for t in terminal[-keep_count:]} if keep_count else set()
    retired=[t for t in terminal if t.id not in keep]
    plan['retired_tasks']=[{'id':t.id,'status':t.status,'source_message_id':t.source_message_id} for t in retired]
    retired_ids={t.id for t in retired};state.tasks=[t for t in state.tasks if t.id not in retired_ids]
    for task in current:
        if len(state.tasks)<100:
            state.tasks.append(task);plan['request_coverage'].append({'request_id':task.request_ids[0],'task_id':task.id,'status':'retained'})
        else:
            plan['deferred_requests'].append(next(r.model_dump(mode='json') for r in u.requests if r.id==task.request_ids[0]))
            plan['request_coverage'].append({'request_id':task.request_ids[0],'status':'capacity_deferred'})
    gateway=ReadTools(db,scope)
    from .sales_policy import policy_context
    attempted=set();results=[];stop='finished';context_signature=digest({'context':resolver.context,
        'policy':policy_context(db,scope,resolver.context['confirmed_project_facts'])})
    current_commercial=any(r.polarity=='request' and r.topic.value not in WRITE_TOPICS|{'other'} for r in u.requests)
    for round_index in range(max_rounds):
        if u.requires_clarification:stop='clarification';break
        eligible=[]
        for task in sorted(state.tasks,key=lambda t:t.source_message_id!=message.id):
            retry=task.status=='blocked' and task.last_read_signature and task.last_read_signature!=context_signature
            if task.id in attempted or task.status not in {'pending','suspended'} and not retry:continue
            if task.source_message_id!=message.id and (task.topic.value in WRITE_TOPICS|{'materials'} or not current_commercial):
                task.status='suspended';continue
            if task.source_message_id!=message.id and task.last_read_signature==context_signature:continue
            if not all(any(d.id==dep and d.status=='completed' for d in state.tasks) for dep in task.depends_on):continue
            eligible.append(task)
        if not eligible:
            stop='finished' if not any(t.status in LIVE for t in state.tasks) else 'no_new_information' if results else 'needs_follow_up'
            break
        evidence=[]
        for task in eligible:
            if task.status=='cancelled':continue
            if clock()-started>=max_seconds:stop='time_limit';break
            if plan['tool_calls']>=max_steps:stop='step_limit';break
            cost=COST.get(task.topic.value,1)
            if plan['read_units']+cost>max_read_units:stop='read_cost_limit';break
            attempted.add(task.id)
            if task.topic.value=='other':task.status='completed';continue
            if task.topic.value in WRITE_TOPICS and not(task.topic.value=='appointment' and u.appointment_query and task.source_message_id==message.id):
                task.status='awaiting_user' if restricted(state,task) else 'pending'
                plan['write_candidates_require_backend_authorization'].append(task.id)
                continue
            if task.binding_status=='unresolved':task.status='awaiting_user';continue
            call=ToolCall(operation_id=task.id,task_id=task.id,topic=task.topic,subject=task.subject,
                property_id=task.property_id,unit_id=task.unit_id,
                appointment_query=u.appointment_query if task.topic.value=='appointment' else None)
            task.status='pending'
            if restricted(state,task) and not call.appointment_query:result=ToolResult(operation_id=task.id,status='denied',safe_message='An explicit restriction blocks this request.')
            else:
                try:result=gateway.execute(call,state)
                except Exception as exc:result=ToolResult(operation_id=task.id,status='error',safe_message=type(exc).__name__)
            plan['tool_calls']+=1;plan['read_units']+=cost
            task.last_read_signature=context_signature
            results.append(result)
            group=task.alternative_group;task.alternative_group=None
            record_result(state,task,result);task.alternative_group=group
            if task.topic.value=='pricing' and any(u.get('price') is None or not u.get('currency') for u in result.data.get('units',[])):
                task.status='blocked'
            # A distributable direct match wins OR; discovery is not delivery.
            match=task.topic.value!='materials' and task.status=='completed' or task.topic.value=='materials' and result.data.get('coverage_confirmed') and any(
                a.get('has_file') or a.get('links') for a in result.data.get('materials',[]))
            if task.alternative_group and match:
                for other in state.tasks:
                    if other.id!=task.id and other.alternative_group==task.alternative_group:other.status='cancelled'
            evidence.append({'task_id':task.id,'status':result.status,'result_sha256':digest(result.model_dump(mode='json'))})
        plan['rounds'].append({'round':round_index+1,'feedback':evidence})
        if stop in {'time_limit','step_limit','read_cost_limit'}:break
        if not evidence:stop='no_new_information';break
    else:stop='round_limit' if any(t.status in {'pending','suspended'} and t.id not in attempted and t.topic.value not in WRITE_TOPICS for t in state.tasks) else 'finished'
    if plan['deferred_requests']:stop='capacity_limit'
    plan['pending_topics']=sorted({t.topic.value for t in state.tasks if t.status in LIVE}|{r['topic'] for r in plan['deferred_requests']})
    plan['context_sha256']=context_signature
    from .monitor import redact
    results=[ToolResult.model_validate(redact(r.model_dump(mode='json'))) for r in results]
    revision,state=save(db,scope,event_key=event_key,expected_revision=revision,state=state,
        metadata={'runtime_version':VERSION,'runtime_fingerprint':fingerprint,'message_id':message.id,
            'results':[r.model_dump(mode='json') for r in results],'plan':plan,'stop_reason':stop,'external_actions':0})
    return PlannedOutcome(revision,state,tuple(results),stop,plan)
