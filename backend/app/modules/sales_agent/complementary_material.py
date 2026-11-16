"""Offer one approved, not-yet-delivered complement for the same property."""
from datetime import datetime,timedelta,timezone

def build(db,scope,state,metadata,channel,holds=()):
    from app.modules.projects.models import ProjectSalesAsset,SalesAssetShare
    from .models import OutboundMessage
    from .material_delivery import snapshot,VERSION
    from .execution import now
    from app.modules.projects.asset_coverage import unrestricted,matches
    from .commercial_context import _safe_asset_links
    current=[b['binding'] for b in metadata.get('material_bindings',[]) if b.get('binding')]
    if not current or not state.selected_property_type_id:return None
    sent={row[0] for row in db.query(SalesAssetShare.sales_asset_id).join(OutboundMessage,OutboundMessage.id==SalesAssetShare.outbound_message_id).filter(SalesAssetShare.company_id==scope.company_id,SalesAssetShare.project_id==scope.project_id,SalesAssetShare.lead_id==scope.lead_id,OutboundMessage.channel==channel,OutboundMessage.status.in_(['sent','delivered','read'])).all()}
    # Simulation receipts and durable conversation metadata also record actual shares.
    from .models import SalesMessage
    from .conversation_scope import scoped_messages_query
    from .dialogue_store import check_scope
    for message in scoped_messages_query(db,check_scope(db,scope)).filter(SalesMessage.direction=='outbound',SalesMessage.status.in_(['sent','delivered','read'])).all():
        sent.update(row['binding']['asset_id'] for row in (message.metadata_json or {}).get('material_bindings',[]) if row.get('binding'))
    sent.update(b['asset_id'] for b in current)
    want='brochure' if any(b['type']=='gallery_image' for b in current) else 'gallery_image'
    candidates=db.query(ProjectSalesAsset).filter_by(company_id=scope.company_id,project_id=scope.project_id,property_type_id=state.selected_property_type_id,asset_type=want).all()
    if any(asset.id in sent for asset in candidates):return None
    for asset in sorted(candidates,key=lambda a:a.id):
        if asset.id in sent or not unrestricted(asset,state,holds=holds):continue
        subject='brochure' if want=='brochure' else 'photos'
        if not any(row['coverage']=='requested_tag' for row in matches(asset,property_id=state.selected_property_type_id,unit_id=state.selected_unit_id,subject=subject)):continue
        targets=([None] if asset.source and asset.source.storage_path else [])
        if want=='gallery_image':targets += [row['url'] for row in _safe_asset_links(asset) if row['kind'] in {'photos','gallery_image'}]
        binding=None
        for target in targets:
            try:binding=snapshot(asset,channel=channel,target_url=target)
            except (ValueError,PermissionError,OSError):continue
            break
        if binding is None:continue
        if want=='brochure' and binding['mime_type']!='application/pdf':continue
        label='the property PDF' if want=='brochure' else 'the property photo gallery'
        question=f'Would you like me to send {label} as well?'
        # Names never establish contents. Only approved descriptions are shown.
        description=asset.description
        if description:question=description.strip()+' '+question
        proposal=dict(version=VERSION,scope=scope.__dict__,expires_at=(now(datetime).replace(tzinfo=timezone.utc)+timedelta(minutes=30)).isoformat(),asset_ids=[asset.id],items=[dict(binding=binding,coverage='requested_tag',property_id=state.selected_property_type_id,task_ids=[],targets=[dict(property_id=state.selected_property_type_id,unit_id=None,subject='brochure' if want=='brochure' else 'photos')],content_types=[want])])
        return dict(id='material_complement',text=question,metadata={'material_offer':proposal,'material_continuity':{'version':'sales-material-continuity/2.1','decision':'offer_complement','property_id':state.selected_property_type_id,'integral_dialogue_quality':'NOT_EVALUATED'}})
    return None
