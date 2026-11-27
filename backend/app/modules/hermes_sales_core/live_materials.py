"""HEI-03B continuation: native live material issue/reconcile boundary.

This is a transactional adapter, not a sender. Only a certified live turn can
issue. The caller must use the existing BlackPenguin provider dispatcher and
bind the returned metadata to the outbox, never log the returned content.
An interrupted issued batch is reviewed, not silently reminted or resent.
"""
from __future__ import annotations
from copy import deepcopy
from urllib.parse import urlsplit
from hashlib import sha256
from datetime import datetime, timezone

from .engine_selection import HERMES, require_selectable
from .production_tools import ProductionToolError, _hash


def material_message(issued, commercial_copy=None):
    """Format exactly the opaque access URLs returned by the BP share service."""
    if not issued or len(issued)>20:
        raise ProductionToolError('Invalid material batch size.')
    lines=['Here are the requested approved materials:']
    for i, item in enumerate(issued,1):
        url=item['url']; name=item['name']
        parsed=urlsplit(url)
        if (parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not parsed.path.rsplit('/',1)[0].endswith('/projects/a')
                or not parsed.path.rsplit('/',1)[-1] or any(c.isspace() for c in url)):
            raise ProductionToolError('Invalid opaque access link returned by share service.')
        # Do not allow material titles to introduce a new link or menu line.
        name=' '.join(str(name or 'Document').split())[:100]
        if '://' in name or '/projects/a/' in name:
            name='Document'
        lines.append(f'{i}. {name}\n{url}')
    from .material_continuity import render_delivery
    return render_delivery('\n'.join(lines),commercial_copy,resource_block='\n'.join(lines[1:]))


def issue_live_material_batch(db,scope,*,inbound_message_id):
    """Issue one bounded batch using existing token service, caller owns commit.

    Returns sensitive customer content only to the authorized dispatch caller.
    No raw token, URL, storage path or file contents are stored in the Hermes
    operation receipt. A durable pending batch must never be reminted.
    """
    require_selectable(HERMES)
    from .production_tools import _load_live_turn, prepare_live_material_batch
    from .bp_operation_models import HermesSalesOperation
    from app.modules.projects.asset_share_service import issue
    conversation,project,lead,inbound,run,reply,receipt,loaded = _load_live_turn(db,scope,inbound_message_id)
    draft = (receipt.state_after.get('offered_assets') or {}).get('pending_request') or {}
    request_id=draft.get('id')
    if not isinstance(request_id,str) or not 1<=len(request_id)<=64:
        raise ProductionToolError('No valid native material request ID.')
    previous=db.query(HermesSalesOperation).filter_by(**scope.__dict__,request_id=request_id).one_or_none()
    if previous:
        # Never mint a new bearer URL on an ambiguous retry. The outbox can
        # contain a committed send even if the final receipt has not been saved.
        raise ProductionToolError('An issued material request already exists; reconcile its original outbox.')
    checked=prepare_live_material_batch(db,scope,inbound_message_id=inbound.id)
    if checked['request_id']!=request_id:
        raise ProductionToolError('Material request changed before issuance.')
    bindings=checked['bindings']
    if not isinstance(bindings,list) or not 1<=len(bindings)<=20 or list(dict.fromkeys(b['asset_id'] for b in bindings))!=draft.get('asset_ids'):
        raise ProductionToolError('Material bindings differ from authorized draft.')
    identities=[(b['asset_id'],b.get('target_url')) for b in bindings]
    if len(set(identities))!=len(identities):
        raise ProductionToolError('Duplicate material targets are not permitted.')
    issued=[]; entries=[]
    for binding in bindings:
        url,share=issue(db,company_id=scope.company_id,project_id=scope.project_id,
            lead_id=scope.lead_id,source_id=binding['source_id'],sales_asset_id=binding['asset_id'],
            channel=conversation.channel,agent_run_id=run.id,expires_in_days=7,target_url=binding.get('target_url'))
        if (not share.id or share.sales_asset_id!=binding['asset_id'] or share.source_id!=binding['source_id']
                or share.company_id!=scope.company_id or share.project_id!=scope.project_id or share.lead_id!=scope.lead_id
                or share.agent_run_id!=run.id or share.channel!=conversation.channel
                or getattr(share,'target_url',None)!=binding.get('target_url')
                or share.token_hash!=sha256(urlsplit(url).path.rsplit('/',1)[-1].encode()).hexdigest()):
            raise ProductionToolError('Share service returned a mismatched scope.')
        issued.append({'url':url,'name':binding['name']})
        entries.append({'share_id':share.id,'binding':deepcopy(binding)})
    content=material_message(issued,draft.get('commercial_copy'))
    ids=[item['share_id'] for item in entries]
    if len(set(ids))!=len(ids):raise ProductionToolError('Share service returned duplicate IDs.')
    group_key='hermes:materials:'+run.id+':'+request_id
    op=HermesSalesOperation(**scope.__dict__,inbound_message_id=inbound.id,request_id=request_id,
        operation_type='material',request_hash=_hash(draft),status='pending_delivery',
        result_json={'status':'issued_not_sent','share_ids':ids,'agent_run_id':run.id,
                     'group_key':group_key,'state_revision':receipt.revision})
    db.add(op);db.flush()
    # Existing dispatch metadata contract. Full material_bindings contain
    # approved file snapshots; pass only to internal outbox, never to model/UI.
    return {'operation_id':op.id,'content':content,'idempotency_key':group_key,
            'metadata':{'engine':'hermes-agent','lead_id':scope.lead_id,'project_id':scope.project_id,
                'agent_run_id':run.id,'hermes_inbound_message_id':inbound.id,
                'continuity_epoch':run.input_snapshot['continuity_epoch'],
                'sales_asset_share_ids':ids,'material_bindings':entries,
                'material_delivery_version':'hermes-native-material/1.0',
                'requested_topics':['materials'],'policy_holds_at_prepare':[]},
            'delivery':'not_sent'}


def complete_live_material_batch(db,scope,*,inbound_message_id,message_ids):
    """Reconcile exact outbox receipts and consume request, without new send."""
    require_selectable(HERMES)
    from .production_tools import _load_live_turn, material_delivery_receipt
    from .bp_operation_models import HermesSalesOperation
    from .bp_state_store import save
    from app.modules.sales_agent.models import SalesMessage
    from app.modules.sales_agent.conversation_scope import scoped_messages_query
    conversation,project,lead,inbound,run,reply,receipt,loaded=_load_live_turn(db,scope,inbound_message_id)
    draft=(receipt.state_after.get('offered_assets') or {}).get('pending_request') or {}
    op=db.query(HermesSalesOperation).filter_by(**scope.__dict__,inbound_message_id=inbound.id,
        operation_type='material',request_id=draft.get('id')).populate_existing().with_for_update().one_or_none()
    if not op or op.status not in {'pending_delivery','completed'} or op.request_hash!=_hash(draft):
        raise ProductionToolError('No matching issued material request.')
    prior=deepcopy(op.result_json or {})
    if prior.get('agent_run_id')!=run.id or prior.get('state_revision')!=receipt.revision:
        raise ProductionToolError('Issued material receipt belongs to another turn.')
    # Every part must belong to the exact generated group, not merely the same
    # run: a provisional reply and a separate asset batch share a run ID.
    if not isinstance(message_ids,list) or not 1<=len(message_ids)<=40:
        raise ProductionToolError('Invalid delivery message IDs.')
    for mid in message_ids:
        row=scoped_messages_query(db,conversation).filter_by(id=mid).one_or_none()
        group=((row.metadata_json or {}).get('delivery_group') or {}) if row else {}
        if group.get('key')!=prior['group_key'] or (row.metadata_json or {}).get('hermes_inbound_message_id')!=inbound.id:
            raise ProductionToolError('Unexpected material delivery group.')
    result=material_delivery_receipt(db,scope,message_ids=message_ids,
        expected_share_ids=prior['share_ids'],channel=conversation.channel)
    if result['agent_run_id']!=run.id:raise ProductionToolError('Unexpected delivery run.')
    if op.status=='completed':
        if prior.get('message_ids')!=message_ids:
            raise ProductionToolError('Completed material receipt has different messages.')
        # Device delivery may be confirmed later; do not mutate immutable
        # conversational state merely because a provider status advanced.
        return {**result,'operation_id':op.id,'replayed':True}
    if loaded.revision!=receipt.revision or loaded.data!=receipt.state_after:
        raise ProductionToolError('Newer Hermes state supersedes material completion; review receipt.')
    state=deepcopy(loaded.data)
    state['offered_assets']={}
    shared=state.setdefault('shared_media',{})
    from app.modules.projects.models import SalesAssetShare
    for sid in prior['share_ids']:
        share=db.get(SalesAssetShare,sid)
        if not share:raise ProductionToolError('Missing issued share.')
        entry=shared.get(share.sales_asset_id) or {}
        previous=entry.get('share_ids') or ([entry['share_id']] if entry.get('share_id') else [])
        if entry.get('source_message_id')!=inbound.id:previous=[]
        ids=list(dict.fromkeys([*previous,sid]))
        shared[share.sales_asset_id]={'share_id':sid,'source_message_id':inbound.id,
            **({'share_ids':ids} if len(ids)>1 else {})}
    committed=save(db,scope,expected_revision=loaded.revision,event_key='hei03b:material:'+op.request_id,
        state=state,event_type='state_update')
    op.status='completed';op.result_json={**prior,'status':result['status'],'message_ids':message_ids,
                                          'completed_state_revision':committed.revision}
    run.output_snapshot={**(run.output_snapshot or {}),'native_live_material':{'operation_id':op.id,
        'share_ids':prior['share_ids'],'message_ids':message_ids,'status':result['status'],
        'state_revision':committed.revision}}
    db.flush()
    return {**result,'operation_id':op.id,'replayed':False}
