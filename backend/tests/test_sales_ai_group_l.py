"""Read-only release preparation; synthetic evidence never authorizes live actions."""
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from pathlib import Path
import hashlib,json,uuid
import pytest
from sqlalchemy import event,text
from test_sales_turn_1720 import case
from test_sales_ai_group_b import agent
from test_sales_ai_group_f import book
from app.modules.sales_agent.dialogue_store import load,save
from tools.sales_ai.release_checklist import template,assess,file_digest,REQUIRED,main as checklist_main
from tools.sales_ai.release_audit import audit,main as audit_main

NOW=datetime(2026,11,9,tzinfo=timezone.utc)


def documented(tmp_path):
    file=tmp_path/'synthetic.txt';file.write_text('Synthetic evidence only, not a real provider acceptance.')
    reference={'path':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    value=template();commit='a'*40
    value.update(candidate_commit=commit,components={key:commit for key in ['api_commit','worker_commit','frontend_commit']})
    value['components'].update(alembic_head='20261109_sales_worker_progress',configuration_sha256='b'*64)
    value['authorization']={'approved':True,'operator':'Synthetic reviewer','environment':'synthetic-no-network','company_id':str(uuid.uuid4()),'project_id':str(uuid.uuid4()),'test_contact_reference':reference,'channels':['sms','whatsapp'],'expires_at':(NOW+timedelta(hours=1)).isoformat()}
    value['checks']={key:{'status':'passed','candidate_commit':commit,'reviewed_by':'Synthetic reviewer','reviewed_at':(NOW-timedelta(minutes=1)).isoformat(),'evidence':[reference]} for key in REQUIRED}
    return value


def test_empty_release_template_is_blocked_without_contact_or_accepted_prerequisites(tmp_path):
    report=assess(template(),tmp_path,now=NOW)
    assert report['status']=='BLOCKED' and 'authorized_test_contact_record_missing_or_changed' in report['blockers']
    assert 'real_model_evaluation:not_passed' in report['blockers'] and not report['deployment_authorized']


def test_complete_synthetic_documents_still_never_claim_provider_verification_or_deployment(tmp_path):
    report=assess(documented(tmp_path),tmp_path,now=NOW)
    assert report['status']=='DOCUMENTS_COMPLETE_OPERATOR_REVIEW_REQUIRED'
    assert not report['deployment_authorized'] and not report['independent_provider_verification'] and report['external_actions']==0


@pytest.mark.parametrize('change', ['expired','missing_whatsapp','different_worker','different_evidence_commit','changed_bytes','no_reviewer','no_receipt','schema_mismatch'])
def test_each_material_release_omission_blocks_document_completeness(tmp_path,change):
    value=documented(tmp_path)
    if change=='expired':value['authorization']['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
    elif change=='missing_whatsapp':value['authorization']['channels']=['sms']
    elif change=='different_worker':value['components']['worker_commit']='c'*40
    elif change=='different_evidence_commit':value['checks']['live_sms']['candidate_commit']='c'*40
    elif change=='changed_bytes':(tmp_path/'synthetic.txt').write_text('changed')
    elif change=='no_reviewer':value['checks']['live_sms']['reviewed_by']=None
    elif change=='no_receipt':value['checks']['lead_delivery_receipts']['status']='pending'
    else:value['components']['alembic_head']='old'
    assert assess(value,tmp_path,now=NOW)['status']=='BLOCKED'


def test_evidence_paths_cannot_escape_the_selected_evidence_directory(tmp_path):
    root=tmp_path/'evidence';root.mkdir();outside=tmp_path/'outside.txt';outside.write_text('private outside fixture')
    reference={'path':'../outside.txt','sha256':hashlib.sha256(outside.read_bytes()).hexdigest()}
    assert not file_digest(root,reference)
    reference['path']=str(outside);assert not file_digest(root,reference)


def test_checklist_cli_never_overwrites_input_and_pending_returns_nonzero(tmp_path):
    source=tmp_path/'checklist.json';source.write_text(json.dumps(template()));before=source.read_bytes()
    assert checklist_main(['--input',str(source),'--evidence-root',str(tmp_path),'--output',str(tmp_path/'result.json')])==2
    assert source.read_bytes()==before
    with pytest.raises(SystemExit):checklist_main(['--input',str(source),'--output',str(source)])


def test_audit_is_select_only_and_does_not_export_credentials_or_change_reservations(agent):
    _,_,meeting,_=book(agent);engine=agent.db.get_bind();before=(meeting.id,meeting.meeting_time,meeting.status)
    agent.config.openrouter_api_key='PRIVATE_CREDENTIAL';agent.db.commit();commands=[]
    def record(conn,cursor,statement,parameters,context,many):commands.append(statement.strip().upper())
    event.listen(engine,'before_cursor_execute',record)
    try:report=audit(engine,agent.company.id,agent.project.id,commit='a'*40,service='api')
    finally:event.remove(engine,'before_cursor_execute',record)
    assert report['status']=='INSPECTED_NOT_ACCEPTED' and report['configuration']['model']=='test/offline'
    assert report['counts']['meetings']=={'confirmed':1} and 'PRIVATE_CREDENTIAL' not in str(report)
    assert not report['acceptance_proven'] and not report['worker_loop_health_proven']
    assert not any(command.startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP')) for command in commands)
    agent.db.refresh(meeting);assert (meeting.id,meeting.meeting_time,meeting.status)==before
    # Audit must restore a pooled SQLite connection's query_only setting.
    agent.company.name='Still writable after read-only audit';agent.db.commit()


def test_audit_pending_proposals_exposes_only_hashes_and_context_kinds(agent):
    from test_sales_ai_group_f import select
    select(agent)
    report=audit(agent.db.get_bind(),agent.company.id,agent.project.id,service='worker')
    pending=report['pending_context_page'];assert len(pending)==1 and pending[0]['contexts']==['booking_proposal']
    assert len(pending[0]['state_sha256'])==64 and 'snapshot_json' not in str(pending) and '100 Main St' not in str(pending)
    assert report['service']=='worker' and report['commit']=='unknown' and not report['acceptance_proven']


def test_audit_refuses_a_foreign_project_without_changing_schema(agent):
    with pytest.raises(PermissionError):audit(agent.db.get_bind(),str(uuid.uuid4()),agent.project.id)
    assert agent.db.execute(text('SELECT count(*) FROM sales_conversations')).scalar()==1


def test_audit_without_database_access_records_blocked_without_connection_attempt(tmp_path,monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False);out=tmp_path/'blocked.json'
    assert audit_main(['--company-id',str(uuid.uuid4()),'--project-id',str(uuid.uuid4()),'--service','api','--output',str(out)])==2
    report=json.loads(out.read_text());assert report['reason']=='DATABASE_URL_MISSING' and report['database_writes']==report['provider_calls']==0


def test_audit_pages_pending_contexts_without_omitting_the_final_page(agent):
    from app.modules.sales_agent.models import SalesConversation
    from app.modules.sales_agent.dialogue_models import SalesDialogueState
    for i in range(101):
        conv=SalesConversation(company_id=agent.company.id,project_id=agent.project.id,lead_id=agent.lead.id,channel='synthetic-'+str(i),is_paused=True)
        agent.db.add(conv);agent.db.flush()
        agent.db.add(SalesDialogueState(id=str(uuid.UUID(int=i+1)),company_id=agent.company.id,project_id=agent.project.id,conversation_id=conv.id,lead_id=agent.lead.id,state_json={'booking_proposal':{'id':'synthetic'}}))
    agent.db.commit()
    first=audit(agent.db.get_bind(),agent.company.id,agent.project.id)
    assert len(first['pending_context_page'])==100 and first['next_state_id']
    second=audit(agent.db.get_bind(),agent.company.id,agent.project.id,after_state_id=first['next_state_id'])
    assert len(second['pending_context_page'])==1 and second['next_state_id'] is None
    assert not {r['state_id'] for r in first['pending_context_page']} & {r['state_id'] for r in second['pending_context_page']}


def test_audit_uses_published_tenant_selection_and_hashes_the_same_pack_as_runtime(agent):
    from test_sales_ai_group_b import publish
    from app.modules.ai_core.models import AIConfiguration
    from app.modules.sales_agent.turn_configuration import resolve
    global_version=publish(agent)
    local=AIConfiguration(company_id=agent.company.id,agent_ventas={'model':'unpublished/model'})
    agent.db.add(local);agent.db.commit()
    first=audit(agent.db.get_bind(),agent.company.id,agent.project.id)
    assert first['configuration']['version_id']==global_version.id
    tenant=publish(agent,{'model':'openai/gpt-4o-mini'},owner=agent.company.id)
    runtime=resolve(agent.db,agent.scope)['source'];second=audit(agent.db.get_bind(),agent.company.id,agent.project.id)
    assert second['configuration']['version_id']==tenant.id
    assert second['configuration']['configuration_sha256']==runtime['configuration_sha256']
    assert second['configuration']['draft_differs_from_published']


def test_audit_does_not_initialize_or_repair_an_incompatible_database():
    from sqlalchemy import create_engine,inspect
    engine=create_engine('sqlite://')
    try:
        report=audit(engine,str(uuid.uuid4()),str(uuid.uuid4()))
        assert report['status']=='INCOMPATIBLE_SCHEMA' and not inspect(engine).get_table_names()
        assert report['database_writes']==0 and report['missing_tables']
    finally:engine.dispose()
