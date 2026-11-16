"""Read-only export of actual commercial graph traces; never reruns a lead turn."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile
from sqlalchemy import create_engine, text


def export(conversation_id, limit=20):
    from app.db.postgres import engine as original
    from app.core.config import settings
    from app.modules.sales_agent.coordinator_graph import VERSION, MODE
    from app.modules.sales_agent.active_service import ENGINE
    engine=create_engine(original.url,connect_args={'connect_timeout':5} if original.dialect.name=='postgresql' else {})
    try:
        with engine.connect() as conn, conn.begin():
            if conn.dialect.name=='postgresql':
                conn.execute(text('SET TRANSACTION READ ONLY'))
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
            conversation=conn.execute(text('SELECT id, company_id, project_id, is_paused, pause_reason FROM sales_conversations WHERE id=:id'),{'id':conversation_id}).mappings().first()
            if conversation is None:raise ValueError('Conversation not found.')
            rows=conn.execute(text('SELECT id, graph_version, status, error_code, started_at, input_snapshot, output_snapshot FROM agent_runs WHERE conversation_id=:id ORDER BY started_at DESC LIMIT :limit'),{'id':conversation_id,'limit':limit}).mappings().all()
            turns=[]
            for row in reversed(rows):
                entry=dict(row)
                def obj(value):return json.loads(value) if isinstance(value,str) else value or {}
                inp=obj(entry.pop('input_snapshot'));out=obj(entry.pop('output_snapshot'))
                message_id=inp.get('message_id')
                message=conn.execute(text('SELECT content FROM sales_messages WHERE id=:message AND conversation_id=:conversation'),{'message':message_id,'conversation':conversation_id}).scalar() if message_id else None
                entry.update(message_id=message_id,lead_message=message,model=inp.get('model'),coordinator_graph=inp.get('coordinator_graph'),
                    observation_loop=inp.get('observation_loop'),understanding=inp.get('understanding'),
                    reply=out.get('reply'),proposed_actions=out.get('proposed_actions'),
                    error_diagnostic=out.get('error_diagnostic'),metadata=out.get('metadata'))
                turns.append(entry)
            return {'read_only':True,'captured_at_utc':datetime.now(timezone.utc).isoformat(),
                'deployed':{'commit':settings.APP_COMMIT_SHA,'engine':ENGINE,'coordinator_version':VERSION,'orchestrator':MODE},
                'conversation':dict(conversation),'turns':turns,
                'note':'Historical turns retain their original engine. A health endpoint does not prove that a turn ran or a message was delivered.'}
    finally:engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation-id',required=True)
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.limit<=50:parser.error('Use 1..50 turns.')
    result=export(args.conversation_id,args.limit)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():parser.error('Use a new output file.')
    with zipfile.ZipFile(args.output,'w',zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr('commercial-graph-review.json',json.dumps(result,default=str,ensure_ascii=False,indent=2))
    args.output.chmod(0o600)
    print(json.dumps({'read_only':True,'turn_count':len(result['turns']),'bundle':str(args.output)}))

if __name__=='__main__':main()
