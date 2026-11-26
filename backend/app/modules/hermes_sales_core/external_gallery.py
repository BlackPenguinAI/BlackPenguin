"""Validate an already issued Hermes gallery redirect at access time.

No provider call, remote fetch or live-engine requirement. Revocation remains
valid after switching engines. The real outbox owns the exact approved binding.
"""
from .production_tools import ProductionToolError


def verify_external_share(db,share,run):
    from app.modules.sales_agent.models import OutboundMessage,SalesMessage
    from app.modules.sales_agent.material_delivery import validate_shares
    from .contracts import TurnScope
    from .provider_delivery import digest_text
    from urllib.parse import urlsplit
    import re
    scope=TurnScope(share.company_id,share.project_id,run.conversation_id,share.lead_id)
    out=db.get(OutboundMessage,share.outbound_message_id) if share.outbound_message_id else None
    if (not out or out.conversation_id!=run.conversation_id or out.agent_run_id!=run.id
            or out.channel!=share.channel or not out.provider_message_id or out.status not in {'sent','accepted','delivered','read','queued','sending'}):
        raise ProductionToolError('Gallery has no attributable provider outbox.')
    rows=db.query(SalesMessage).filter_by(conversation_id=run.conversation_id,direction='outbound',role='assistant',channel=share.channel).filter(
        SalesMessage.metadata_json['outbound_message_id'].as_string()==out.id).all()
    if len(rows)!=1:raise ProductionToolError('Gallery has no exact visible message.')
    row=rows[0];meta=row.metadata_json or {}
    if (meta.get('engine')!='hermes-agent' or meta.get('hermes_delivery_kind')!='material'
            or meta.get('agent_run_id')!=run.id or meta.get('lead_id')!=share.lead_id or meta.get('project_id')!=share.project_id
            or row.provider_message_id!=out.provider_message_id or row.content!=out.content or share.id not in (meta.get('sales_asset_share_ids') or [])
            or row.status not in {'sent','accepted','delivered','read','queued','sending'}):
        raise ProductionToolError('Gallery receipt no longer matches the provider message.')
    group=meta.get('delivery_group') or {};plan=((run.output_snapshot or {}).get('hermes_delivery_plans') or {}).get(group.get('key'))
    from .provider_delivery import verify_plan_part
    if not plan or plan.get('kind')!='material':raise ProductionToolError('Gallery delivery plan missing.')
    verify_plan_part(plan,meta,row.content,out.idempotency_key)
    hashes={digest_text(t.rstrip('.,;)')) for t in re.findall(r'/projects/a/([^\s]+)',row.content)}
    if share.token_hash not in hashes or urlsplit(share.target_url).scheme!='https' or not validate_shares(db,scope,[share],meta,subset=True):
        raise ProductionToolError('Approved gallery URL changed or expired.')
