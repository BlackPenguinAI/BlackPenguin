"""Read-only Telnyx route/history diagnostic; never sends or changes tenant data."""
import argparse,json,re
from sqlalchemy import create_engine,text


def inspect(engine,*,sender,recipient,channel):
    if not all(re.fullmatch(r'\+[1-9][0-9]{6,14}',v) for v in (sender,recipient)):
        raise ValueError('Use complete E.164 sender and recipient numbers.')
    if channel not in {'sms','whatsapp'}:raise ValueError('Use sms or whatsapp.')
    key=f'telnyx:{sender}:{recipient}' if channel=='sms' else f'telnyx:whatsapp:{sender}:{recipient}'
    with engine.connect() as connection:
        if connection.dialect.name!='postgresql':raise ValueError('This diagnostic requires PostgreSQL.')
        with connection.begin():
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            owners=connection.execute(text('''
                SELECT c.name AS company,t.company_id,t.live_sms_enabled,t.live_whatsapp_enabled,
                       t.verification_status,t.whatsapp_verification_status
                FROM telnyx_company_configurations t JOIN companies c ON c.id=t.company_id
                WHERE (CASE WHEN :channel='whatsapp' THEN t.whatsapp_from_phone_number ELSE t.from_phone_number END)=:sender
            '''),{'channel':channel,'sender':sender}).mappings().all()
            conversations=connection.execute(text('''
                SELECT sc.id AS conversation_id,c.name AS company,sc.company_id,sc.lead_id,
                       sc.is_paused,sc.pause_reason,l.deleted_at AS lead_deleted_at,
                       sc.provider_thread_key=:key AS active_route,
                       sc.continuity_json->'retired_provider_route' AS retired_route,
                       (SELECT count(*) FROM sales_inbound_jobs j WHERE j.conversation_id=sc.id
                         AND j.status IN ('pending','retry','processing','awaiting_resume')) AS pending_inbound,
                       (SELECT count(*) FROM sales_follow_up_jobs j WHERE j.conversation_id=sc.id
                         AND j.status IN ('pending','retry','processing')) AS pending_followups,
                       (SELECT count(*) FROM outbound_messages o WHERE o.conversation_id=sc.id
                         AND o.status IN ('draft','pending','queued','retry','scheduled')) AS pending_outbound
                FROM sales_conversations sc JOIN companies c ON c.id=sc.company_id
                LEFT JOIN leads l ON l.id=sc.lead_id
                WHERE sc.provider='telnyx' AND sc.channel=:channel AND
                  (sc.provider_thread_key=:key OR sc.continuity_json->'retired_provider_route'->>'provider_thread_key'=:key)
                ORDER BY sc.created_at LIMIT 30
            '''),{'channel':channel,'key':key}).mappings().all()
    return {'read_only':True,'sender_owners':[dict(r) for r in owners],
        'conversations':[dict(r) for r in conversations],
        'active_route_count':sum(r['active_route'] is True for r in conversations),
        'active_route_matches_current_owner':bool(len(owners)==1 and sum(r['active_route'] is True for r in conversations)==1 and all(r['company_id']==owners[0]['company_id'] for r in conversations if r['active_route'] is True)),
        'note':'Run after retrying lead registration. The old route is retired lazily for disconnections made before this fix. This does not prove message delivery.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sender',required=True);parser.add_argument('--recipient',required=True)
    parser.add_argument('--channel',choices=['sms','whatsapp'],required=True);args=parser.parse_args()
    from app.db.postgres import engine as original
    engine=create_engine(original.url,connect_args={'connect_timeout':5})
    try:print(json.dumps(inspect(engine,**vars(args)),indent=2,default=str,ensure_ascii=False))
    finally:engine.dispose()


if __name__=='__main__':main()
