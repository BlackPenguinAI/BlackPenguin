"""Group 5: typed, revalidated read tools. External writes are intentionally denied."""
import hashlib
import json
from .understanding_contract import StrictModel, Topic, Subject, ToolResult
from .dialogue_tasks import restricted
from .dialogue_store import check_scope, DialogueConflict
from .commercial_context import build_commercial_context
from app.modules.projects.models import Project
from pydantic import Field
from .property_comparison import ComparisonRead


class ToolCall(StrictModel):
    operation_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=60)
    topic: Topic
    subject: Subject | None = None
    property_id: str | None = Field(default=None, max_length=36)
    unit_id: str | None = Field(default=None,max_length=36)
    appointment_query: str | None = Field(default=None,max_length=20)
    comparison: ComparisonRead | None = None


FACTS = {'financing':'payment_methods', 'delivery':'delivery_dates', 'amenities':'amenities', 'location':'exact_address'}
EFFECT_TOPICS = {Topic.appointment, Topic.human, Topic.opt_out}


class ReadTools:
    """Per-turn operation ledger. Read results are revalidated even on retry."""
    def __init__(self, db, scope):
        self.db, self.scope, self.ledger = db, scope, {}

    def execute(self, call, state):
        call = ToolCall.model_validate(call)
        conversation = check_scope(self.db, self.scope)
        digest = hashlib.sha256(json.dumps(call.model_dump(mode='json'), sort_keys=True).encode()).hexdigest()
        if call.operation_id in self.ledger and self.ledger[call.operation_id] != digest:
            raise DialogueConflict('Operation ID reused with different arguments.')
        self.ledger[call.operation_id] = digest
        task = next((t for t in state.tasks if t.id == call.task_id), None)
        def result(status, **kwargs):
            return ToolResult(operation_id=call.operation_id, status=status, **kwargs)
        from .next_flow import selected
        next_enabled=selected(self.scope)
        appointment_read=next_enabled and call.topic==Topic.appointment and call.appointment_query
        if not task or task.topic != call.topic or task.subject != call.subject or restricted(state, task) and not appointment_read:
            return result('denied', safe_message='The request is not authorized by the current task and restrictions.')
        if task.status not in {'pending', 'suspended'}:
            return result('denied', safe_message='This task is not executable.')
        if next_enabled and task.binding_status=='resolved' and (task.property_id!=call.property_id or task.unit_id!=call.unit_id):
            return result('denied',safe_message='Tool target does not match the validated request binding.')
        if call.topic in EFFECT_TOPICS and not appointment_read:
            return result('denied', safe_message='External actions are disabled in this staged runtime.')
        context = build_commercial_context(self.db, project=self.db.get(Project, self.scope.project_id),
            company_id=self.scope.company_id, lead_id=self.scope.lead_id, channel=conversation.channel)
        from .sales_policy import policy_context, compliance_action_holds
        holds = compliance_action_holds(policy_context(self.db,self.scope,context['confirmed_project_facts']))
        if call.topic.value in holds:
            return result('denied', safe_message='This action needs Sales review under approved guidance; the conversation remains active.')
        if call.comparison:
            if call.topic != Topic.catalog or not state.last_understanding or call.comparison.directive != state.last_understanding.comparison:
                return result('denied',safe_message='Comparison does not match the current request.')
            from .property_comparison import render
            text, properties, units = render(call.comparison, context, state, holds)
            return result('success' if properties or units else 'uncertain', evidence_ids=properties+units,
                data={'comparison_text':text, 'comparison_property_ids':properties, 'comparison_unit_ids':units})
        if appointment_read:
            from .appointment_context import AppointmentReadTool
            return result('success',data={'appointment_query':AppointmentReadTool(self.db,self.scope).execute({'category':call.appointment_query})})
        types = context['property_types']
        if call.property_id and call.property_id not in {p['id'] for p in types}:
            return result('revoked', safe_message='The selected property is no longer in the approved catalog.')
        unit=next((u for u in context['inventory'] if u['id']==call.unit_id and u.get('unit_code')),None) if call.unit_id else None
        if call.unit_id and not unit:return result('revoked',safe_message='The unit is not in the approved inventory.')
        if call.topic == Topic.materials:
            matches = []
            for asset in context['available_assets']:
                selected = next((p['property_type'] for p in types if p['id'] == call.property_id), None)
                if next_enabled:
                    from app.modules.projects.models import ProjectSalesAsset
                    row=self.db.get(ProjectSalesAsset,asset['asset_id'])
                    if row.property_type_id and row.property_type_id != call.property_id:continue
                if selected and asset.get('property_type') and asset['property_type'] != selected:
                    continue
                if next_enabled:
                    from .material_delivery import snapshot
                    from app.modules.projects.models import ProjectSalesAsset
                    row=self.db.get(ProjectSalesAsset,asset['asset_id'])
                    file_ok=False
                    if asset.get('has_file'):
                        try:snapshot(row,channel=conversation.channel);file_ok=True
                        except (ValueError,OSError):pass
                    links=[]
                    for link in asset['links']:
                        try:snapshot(row,channel=conversation.channel,target_url=link['url']);links.append(link)
                        except (ValueError,OSError):pass
                    asset={**asset,'has_file':file_ok,'links':links}
                    if not file_ok and not links:continue
                tags = set(asset['content_tags'])
                direct = call.subject is None or call.subject in tags or call.subject in asset.get('capabilities', [])
                direct |= call.subject == 'photos' and 'gallery_image' in tags
                fallback = call.subject == 'photos' and bool(tags & {'brochure','gallery_image'})
                if direct or fallback:
                    links = [link for link in asset['links'] if link['kind'] == call.subject]
                    matches.append({**asset, 'links':links, 'coverage':'type_only_unit_unconfirmed' if unit else 'requested_tag' if direct else 'possible_embedded_photos'})
            if next_enabled and not call.property_id and len({a.get('property_type') for a in matches if a.get('property_type')})>1:
                return result('uncertain',safe_message='Which property should these materials cover?')
            complete = all(a['coverage']=='requested_tag' for a in matches)
            return result(('success' if complete else 'partial') if matches else 'empty', evidence_ids=[a['asset_id'] for a in matches],
                data={'materials':matches, 'delivery':'not_sent','requested_unit_id':call.unit_id, 'coverage_confirmed':all(a['coverage']=='requested_tag' for a in matches)})
        if call.topic in {Topic.catalog, Topic.property_details, Topic.pricing, Topic.inventory}:
            if call.topic == Topic.property_details and not call.property_id and not unit:
                return result('uncertain', safe_message='Select a property before requesting its details.')
            rows = [p for p in types if p['id'] == call.property_id] if call.property_id else [] if unit else types
            return result('partial' if rows or unit else 'empty', evidence_ids=[p['id'] for p in rows]+([unit['id']] if unit else []),
                data={'property_types':rows, 'coverage':context['catalog_coverage'],
                      'inventory':[unit] if unit else context['inventory'] if call.topic == Topic.inventory else [],
                      'units':[unit] if unit else [],
                      'inventory_source':context['inventory_source']})
        facts = context['confirmed_project_facts']
        key = FACTS.get(call.topic.value)
        value = facts.get(key) if key else None
        if call.topic == Topic.location:
            address=facts.get('exact_address')
            if isinstance(address,list):
                address='; '.join(v if isinstance(v,str) else v.get('address','') for v in address if isinstance(v,(str,dict)))
            parts=[v.strip() for v in (address,facts.get('city'),facts.get('country')) if isinstance(v,str) and v.strip()]
            value = ', '.join(dict.fromkeys(parts)) or facts.get('location')
        if call.topic == Topic.delivery and any(c.get('code') == 'ready_status_future_delivery'
                                               for c in context['data_conflicts'] if isinstance(c, dict)):
            return result('conflict', safe_message='Approved delivery information needs reconciliation.')
        if call.topic == Topic.delivery and not value:
            key, value = 'delivery_timeline', facts.get('delivery_timeline')
        return result('success' if value else 'empty', data={'field':key, 'value':value,
            'provenance':context['fact_provenance'].get(key)})
