"""Internal failure auditing and customer-facing assistance; no implicit handoff."""
from .models import AgentRun
from .conversation_scope import scoped_messages_query


def response(db, conversation, run):
    prior = db.query(AgentRun).filter(AgentRun.conversation_id == conversation.id,
        AgentRun.id != run.id).order_by(AgentRun.started_at.desc(), AgentRun.id.desc()).limit(10).all()
    failed = []
    for item in prior:
        identifier = (item.input_snapshot or {}).get('message_id')
        if not scoped_messages_query(db, conversation).filter_by(id=identifier).first():
            continue
        if not item.error_code:
            break
        failed.append(item)
    count = len(failed) + 1
    if count == 1:
        return "Would you like me to connect you with the sales team to help with your question?", False, count
    from app.modules.governance.services import enqueue_notification
    enqueue_notification(db, company_id=conversation.company_id, project_id=conversation.project_id,
        event_type='sales_processing_issue', entity_type='sales_conversation', entity_id=conversation.id,
        payload={'title':'Sales conversation needs a system review',
                 'body':'Repeated interpretation failures. The AI remains active; review the diagnostic trace.',
                 'action_url':'/app/agent','recipient_roles':['admin','assistant'],
                 'conversation_id':conversation.id,'error_code':run.error_code},
        dedupe_key='sales-processing-issue:'+conversation.id+':'+(failed[-1].id if failed else run.id))
    return ("Would you prefer to continue here or speak with the sales team?", False, count)
