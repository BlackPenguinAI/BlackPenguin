"""Group 5: typed, revalidated read tools. External writes are intentionally denied."""
import hashlib
import json
from .understanding_contract import StrictModel, Topic, Subject, ToolResult
from .dialogue_tasks import restricted
from .dialogue_store import check_scope, DialogueConflict
from .commercial_context import build_commercial_context
from app.modules.projects.models import Project
from pydantic import Field


class ToolCall(StrictModel):
    operation_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=60)
    topic: Topic
    subject: Subject | None = None
    property_id: str | None = Field(default=None, max_length=36)


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
        if not task or task.topic != call.topic or task.subject != call.subject or restricted(state, task):
            return result('denied', safe_message='The request is not authorized by the current task and restrictions.')
        if task.status not in {'pending', 'suspended'}:
            return result('denied', safe_message='This task is not executable.')
        if call.topic in EFFECT_TOPICS:
            return result('denied', safe_message='External actions are disabled in this staged runtime.')
        context = build_commercial_context(self.db, project=self.db.get(Project, self.scope.project_id),
            company_id=self.scope.company_id, lead_id=self.scope.lead_id, channel=conversation.channel)
        from .sales_policy import policy_context, compliance_action_holds
        holds = compliance_action_holds(policy_context(self.db,self.scope,context['confirmed_project_facts']))
        if call.topic.value in holds:
            return result('denied', safe_message='This action needs Sales review under approved guidance; the conversation remains active.')
        types = context['property_types']
        if call.property_id and call.property_id not in {p['id'] for p in types}:
            return result('revoked', safe_message='The selected property is no longer in the approved catalog.')
        if call.topic == Topic.materials:
            matches = []
            for asset in context['available_assets']:
                selected = next((p['property_type'] for p in types if p['id'] == call.property_id), None)
                if selected and asset.get('property_type') and asset['property_type'] != selected:
                    continue
                tags = set(asset['content_tags'])
                direct = call.subject is None or call.subject in tags or call.subject in asset.get('capabilities', [])
                direct |= call.subject == 'photos' and 'gallery_image' in tags
                fallback = call.subject == 'photos' and bool(tags & {'brochure','gallery_image'})
                if direct or fallback:
                    links = [link for link in asset['links'] if link['kind'] == call.subject]
                    matches.append({**asset, 'links':links, 'coverage':'requested_tag' if direct else 'possible_embedded_photos'})
            complete = all(a['coverage']=='requested_tag' for a in matches)
            return result(('success' if complete else 'partial') if matches else 'empty', evidence_ids=[a['asset_id'] for a in matches],
                data={'materials':matches, 'delivery':'not_sent', 'coverage_confirmed':all(a['coverage']=='requested_tag' for a in matches)})
        if call.topic in {Topic.catalog, Topic.property_details, Topic.pricing, Topic.inventory}:
            if call.topic == Topic.property_details and not call.property_id:
                return result('uncertain', safe_message='Select a property before requesting its details.')
            rows = [p for p in types if p['id'] == call.property_id] if call.property_id else types
            return result('partial' if rows else 'empty', evidence_ids=[p['id'] for p in rows],
                data={'property_types':rows, 'coverage':context['catalog_coverage'],
                      'inventory':context['inventory'] if call.topic == Topic.inventory else [],
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
