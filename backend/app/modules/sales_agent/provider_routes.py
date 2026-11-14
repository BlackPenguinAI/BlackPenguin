"""Retire active Telnyx route bindings without moving tenant history.

The unique provider thread key is an active routing identity. Its archived value
stays inside the old conversation; no messages or lead contexts are reassigned.
"""
from datetime import datetime
import hashlib
from fastapi import HTTPException
from sqlalchemy import text


def retired(conversation):
    return bool(conversation and (conversation.continuity_json or {}).get('retired_provider_route'))


def parts(conversation):
    key=conversation.provider_thread_key
    if not key or conversation.provider!='telnyx':return None
    values=key.split(':')
    if conversation.channel=='sms' and len(values)==3 and values[0]=='telnyx':return values[1],values[2]
    if conversation.channel=='whatsapp' and len(values)==4 and values[:2]==['telnyx','whatsapp']:return values[2],values[3]
    return None


def _phone(value):
    import re
    return re.sub(r'[^0-9]','',value or '')


def _sender(config,channel):
    return config.whatsapp_from_phone_number if channel=='whatsapp' else config.from_phone_number


def assert_dispatchable(db,conversation):
    if retired(conversation):raise HTTPException(409,'This sender route was retired. Start a new conversation under its current Company.')
    identity=parts(conversation)
    if not identity:return
    from app.modules.system_settings.models import TelnyxCompanyConfig
    configs=db.query(TelnyxCompanyConfig).populate_existing().all()
    owner=next((c for c in configs if _phone(_sender(c,conversation.channel))==_phone(identity[0])),None)
    own=next((c for c in configs if c.company_id==conversation.company_id),None)
    if (owner and owner.company_id!=conversation.company_id) or (own and _phone(_sender(own,conversation.channel))!=_phone(identity[0])):
        raise HTTPException(409,'This Company no longer owns the conversation sender. Its historical conversation cannot be resumed or sent.')


def retire(db,conversation,reason):
    if retired(conversation):return
    from .continuity import state
    from .models import SalesInboundJob,SalesFollowUpJob,OutboundMessage
    key=conversation.provider_thread_key
    # Retirement also applies to deleted opportunities: do not reopen their
    # dialogue store (which deliberately rejects deleted leads). The permanent
    # route marker and epoch invalidate every old action/offer instead.
    value=state(conversation)
    value.update(epoch=value['epoch']+1,waiting_for_lead=False,offer_barrier=True)
    conversation.pending_asset_id=None;conversation.pending_asset_offered_at=None
    value['retired_provider_route']={'provider_thread_key':key,'retired_at_utc':datetime.utcnow().isoformat(),'reason':reason}
    conversation.continuity_json=value;conversation.provider_thread_key=None
    conversation.is_paused=True;conversation.pause_reason=reason
    now=datetime.utcnow()
    for model in (SalesInboundJob,SalesFollowUpJob):
        db.query(model).filter(model.conversation_id==conversation.id,model.status.in_(['pending','retry','processing','awaiting_resume'])).update({'status':'cancelled','processed_at':now},synchronize_session=False)
    db.query(OutboundMessage).filter(OutboundMessage.conversation_id==conversation.id,OutboundMessage.status.in_(['draft','pending','queued','retry','scheduled'])).update({'status':'cancelled','last_error':reason},synchronize_session=False)
    # An already-started provider request is not proof of non-delivery. Keep its
    # receipt/status for review; the retired route forbids automatic resend.
    db.flush()


def release_stale_conflict(db,*,thread_key,company_id,provider,channel):
    """Atomically release only a route whose sender left the old Company.

    A paused/deleted lead alone is NOT sufficient. The current Company must have
    the enabled, verified Telnyx identity and the previous Company must lack it.
    """
    from .models import SalesConversation
    from app.modules.system_settings.models import TelnyxCompanyConfig
    if db.get_bind().dialect.name=='postgresql':
        from .concurrency import bounded
        bounded(db)
        lock=int.from_bytes(hashlib.sha256(thread_key.encode()).digest()[:8],'big',signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock})
    conflict=db.query(SalesConversation).filter_by(provider_thread_key=thread_key).populate_existing().with_for_update().first()
    if not conflict or conflict.company_id==company_id:return conflict
    identity=parts(conflict)
    if provider!='telnyx' or not identity or channel!=conflict.channel:return conflict
    configs=db.query(TelnyxCompanyConfig).filter(TelnyxCompanyConfig.company_id.in_([company_id,conflict.company_id])).populate_existing().all()
    current=next((c for c in configs if c.company_id==company_id),None)
    old=next((c for c in configs if c.company_id==conflict.company_id),None)
    if not current or _phone(_sender(current,channel))!=_phone(identity[0]):return conflict
    ready=(current.live_whatsapp_enabled and current.whatsapp_verification_status=='verified') if channel=='whatsapp' else (current.live_sms_enabled and current.verification_status=='verified')
    if not ready or old and _phone(_sender(old,channel))==_phone(identity[0]):return conflict
    retire(db,conflict,'Sender route retired after verified reassignment to another Company.')
    return None
